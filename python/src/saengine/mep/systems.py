"""Connector-based MEP systems, connectivity checks, totals and BCF export (Revit-parity R8).

Builds logical MEP networks from explicit :class:`saengine.library.mep.Connector` ports or
connectors derived automatically from run endpoints, risers, equipment and terminals in
``07 MEP/mep.json``.

- Snap-connects ports whose positions coincide within ``tolerance`` (point-to-point, T-tap onto a
  run's centreline, vertical riser branch tap, and equipment footprint contacts).
- Traverses the graph from sources (AHU, chiller, pump, tank, distribution board, transformer,
  generator, fire pump, ...) to form logical systems by classification.
- Totals airflow [l/s], water flow [l/s], fixture units and electrical load [kW] (reusing
  :mod:`saengine.hvac.air`, :mod:`saengine.plumbing.demand` and :mod:`saengine.electrical.demand`),
  plus critical path length [m].
- Checks open connectors, unassigned elements, mixed classifications, flow direction conflicts
  and size mismatches, and converts findings to coordination / BCF 3.0 issues.
"""

from __future__ import annotations

import heapq
import itertools
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Point

from saengine.library.mep import (
    MEP_FILE,
    SYSTEM_CLASSIFICATIONS,
    Coordination,
    MepModel,
    parse,
)
from saengine.mep.geometry import inside, rotated_rectangle
from saengine.mep.routing import path_length

#: Default snap tolerance between connector points [mm].
DEFAULT_TOLERANCE = 50.0
#: Size difference above which direct inline connections flag a mismatch [mm].
SIZE_TOLERANCE = 1.0
#: Default ceiling elevation above floor when soffit / story above is unknown [mm].
_DEFAULT_CEILING_OFFSET = 2700.0
_DUCT_HANGER = 25.0
_TRAY_HEADROOM = 150.0
_SLAB_FALLBACK = 150.0

AIR_CLASSIFICATIONS = frozenset(
    {"supplyAir", "returnAir", "exhaustAir", "freshAir", "kitchenExhaust", "smokeExtract"}
)
WATER_CLASSIFICATIONS = frozenset(
    {
        "chilledWater",
        "condenserWater",
        "domesticColdWater",
        "domesticHotWater",
        "sanitary",
        "vent",
        "stormWater",
        "fireProtection",
    }
)
ELECTRICAL_CLASSIFICATIONS = frozenset({"power", "cableTray"})

_DUCT_TO_CLASS: dict[str, str] = {
    "supply": "supplyAir",
    "return": "returnAir",
    "exhaust": "exhaustAir",
    "freshAir": "freshAir",
    "kitchenExhaust": "kitchenExhaust",
    "smoke": "smokeExtract",
}

_PLUMBING_TO_CLASS: dict[str, str] = {
    "coldWater": "domesticColdWater",
    "hotWater": "domesticHotWater",
    "soil": "sanitary",
    "waste": "sanitary",
    "soilWaste": "sanitary",
    "vent": "vent",
    "rainwater": "stormWater",
    "pumpMain": "domesticColdWater",
    "chilledWater": "chilledWater",
    "condenserWater": "condenserWater",
    "fireProtection": "fireProtection",
}

_EQUIP_ROLE: dict[str, tuple[str, str, str, bool]] = {
    # kind -> (domain, classification, direction, is_source)
    "ahu": ("duct", "supplyAir", "out", True),
    "freshAirUnit": ("duct", "freshAir", "out", True),
    "exhaustFan": ("duct", "exhaustAir", "in", True),
    "fcu": ("duct", "supplyAir", "out", True),
    "chiller": ("pipe", "chilledWater", "out", True),
    "coolingTower": ("pipe", "condenserWater", "bidirectional", True),
    "pump": ("pipe", "domesticColdWater", "out", True),
    "tank": ("pipe", "domesticColdWater", "out", True),
    "vrfOutdoor": ("pipe", "chilledWater", "out", True),
    "splitOutdoor": ("pipe", "chilledWater", "out", True),
    "generator": ("electrical", "power", "out", True),
    "transformer": ("electrical", "power", "out", True),
    "switchgear": ("electrical", "power", "out", True),
    "lvPanel": ("electrical", "power", "out", True),
    "distributionBoard": ("electrical", "power", "out", True),
    "ups": ("electrical", "power", "out", True),
    "solarPv": ("electrical", "power", "out", True),
    "battery": ("electrical", "power", "bidirectional", True),
    "capacitorBank": ("electrical", "power", "in", False),
    "fuelTank": ("pipe", "domesticColdWater", "out", False),
    "lift": ("electrical", "power", "in", False),
    "other": ("electrical", "power", "in", False),
}

_MULTI_PORT_HVAC_ACCEPT: dict[str, tuple[str, ...]] = {
    "ahu": ("supplyAir", "returnAir", "freshAir", "chilledWater", "condenserWater"),
    "fcu": ("supplyAir", "returnAir", "chilledWater"),
    "chiller": ("chilledWater", "condenserWater"),
}


@dataclass
class Port:
    """One resolved connector port on an MEP element."""

    key: str  # "<element_id>:<port_id>"
    element_id: str
    port_id: str
    domain: str
    classification: str
    shape: str
    direction: str  # "in" | "out" | "bidirectional"
    x: float
    y: float
    z: float
    z_explicit: bool
    story: str | None
    width: float | None = None
    height: float | None = None
    diameter: float | None = None
    flow: float | None = None  # [l/s]
    fixture_units: float | None = None
    load: float | None = None  # [kW]
    circuit: str | None = None
    system_name: str = ""
    connected_to: str | None = None
    station: float = 0.0  # distance along a run's polyline [mm]
    derived: bool = True

    @property
    def size_label(self) -> str:
        if self.diameter is not None:
            return f"Ø{self.diameter:g} mm"
        if self.width is not None and self.height is not None:
            return f"{self.width:g}×{self.height:g} mm"
        if self.width is not None:
            return f"{self.width:g} mm"
        return ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.port_id,
            "elementId": self.element_id,
            "domain": self.domain,
            "classification": self.classification,
            "shape": self.shape,
            "direction": self.direction,
            "point": [round(self.x, 1), round(self.y, 1), round(self.z, 1)],
            "story": self.story,
            "width": self.width,
            "height": self.height,
            "diameter": self.diameter,
            "flow": self.flow,
            "fixtureUnits": self.fixture_units,
            "load": self.load,
            "derived": self.derived,
        }


@dataclass
class ElementNode:
    """An MEP element participating in logical systems."""

    id: str
    kind: str
    discipline: str
    story: str | None
    domain: str
    classification: str
    is_source: bool = False
    is_terminal: bool = False
    is_run: bool = False
    is_riser: bool = False
    path: list[tuple[float, float]] = field(default_factory=list)
    run_z: float | None = None
    z_low: float | None = None
    z_high: float | None = None
    stories_passed: list[str] = field(default_factory=list)
    footprint: list[tuple[float, float]] | None = None
    flow: float | None = None  # [l/s]
    fixture_units: float | None = None
    load: float | None = None  # [kW]
    capacity: float | None = None
    ports: list[Port] = field(default_factory=list)
    has_explicit_connectors: bool = False
    equipment_kind: str = ""
    serves: list[str] | None = None

    @property
    def anchor(self) -> list[float] | None:
        if self.ports:
            p = self.ports[0]
            return [round(p.x, 1), round(p.y, 1), round(p.z, 1)]
        return None


@dataclass
class Connection:
    """A snapped or explicit connection between two ports."""

    a: Port
    b: Port
    is_tee: bool = False

    @property
    def point(self) -> list[float]:
        return [
            round((self.a.x + self.b.x) / 2, 1),
            round((self.a.y + self.b.y) / 2, 1),
            round((self.a.z + self.b.z) / 2, 1),
        ]


def _story_levels(
    mep: MepModel, building: Any = None
) -> tuple[dict[str, float], list[str], dict[str, float]]:
    """Returns (story -> elevation mm, ordered story ids, story -> soffit elevation mm)."""
    levels: dict[str, float] = {}
    order: list[str] = []
    soffits: dict[str, float] = {}
    if building is not None and getattr(building, "stories", None):
        ordered = sorted(building.stories, key=lambda s: s.elevation)
        levels = {s.id: float(s.elevation) for s in ordered}
        order = [s.id for s in ordered]
        slab_thick: dict[float, float] = {}
        for elem in getattr(building, "elements", []) or []:
            if getattr(elem, "kind", None) == "slab":
                slab_thick[float(elem.elevation)] = max(
                    slab_thick.get(float(elem.elevation), 0.0), _SLAB_FALLBACK
                )
        for i, sid in enumerate(order[:-1]):
            top_elev = levels[order[i + 1]]
            soffits[sid] = top_elev - slab_thick.get(top_elev, _SLAB_FALLBACK)
        return levels, order, soffits

    seen: list[str] = []
    for entry in (
        *(mep.equipment or []),
        *(mep.hvac.plant if mep.hvac else []),
        *(mep.hvac.ducts if mep.hvac else []),
        *(mep.hvac.terminals if mep.hvac else []),
        *(mep.hvac.pipes if mep.hvac else []),
        *(mep.plumbing.pipes if mep.plumbing else []),
        *(mep.plumbing.tanks if mep.plumbing else []),
        *(mep.electrical.equipment if mep.electrical else []),
        *(mep.electrical.trays if mep.electrical else []),
        *(mep.fire.mains if mep.fire else []),
        *(mep.fire.pumps if mep.fire else []),
        *(mep.fire.sprinklerPipes if mep.fire else []),
        *(mep.fire.sprinklerHeads if mep.fire else []),
    ):
        story = getattr(entry, "story", None)
        if story and story not in seen:
            seen.append(story)
    for riser in (
        *(mep.plumbing.risers if mep.plumbing else []),
        *(mep.electrical.risers if mep.electrical else []),
        *(mep.fire.risers if mep.fire else []),
    ):
        for s in (riser.fromStory, riser.toStory):
            if s and s not in seen:
                seen.append(s)
    for i, sid in enumerate(seen):
        levels[sid] = i * 3200.0
    order = seen
    return levels, order, soffits


def _stories_between(order: list[str], levels: dict[str, float], low: str, high: str) -> list[str]:
    if low in levels and high in levels:
        z0, z1 = min(levels[low], levels[high]), max(levels[low], levels[high])
        return sorted(
            (s for s, z in levels.items() if z0 - 1.0 <= z <= z1 + 1.0), key=levels.__getitem__
        )
    if low in order and high in order:
        i, j = order.index(low), order.index(high)
        lo, hi = min(i, j), max(i, j)
        return order[lo : hi + 1]
    return [s for s in dict.fromkeys((low, high)) if s]


def _run_z(
    story: str | None,
    bottom: float | None,
    height: float,
    gap: float,
    levels: dict[str, float],
    soffits: dict[str, float],
) -> tuple[float, bool]:
    floor = levels.get(story or "", 0.0)
    if bottom is not None:
        return floor + float(bottom) + height / 2.0, True
    if story and story in soffits:
        return soffits[story] - gap - height / 2.0, False
    return floor + _DEFAULT_CEILING_OFFSET, False


def _footprint_of(item: Any) -> list[tuple[float, float]] | None:
    length = getattr(item, "length", None)
    width = getattr(item, "width", None)
    if not length or not width:
        return None
    rotation = float(getattr(item, "rotation", 0.0) or 0.0)
    return rotated_rectangle(float(item.x), float(item.y), float(length), float(width), rotation)


def _explicit_ports(
    raw_item: Any,
    elem_id: str,
    default_x: float,
    default_y: float,
    default_z: float,
    default_story: str | None,
    path: list[tuple[float, float]] | None = None,
) -> list[Port]:
    ports: list[Port] = []
    line = LineString(path) if path and len(path) >= 2 else None
    for idx, c in enumerate(getattr(raw_item, "connectors", None) or [], start=1):
        port_id = c.id or f"C{idx}"
        px = float(c.x) if c.x is not None else default_x
        py = float(c.y) if c.y is not None else default_y
        pz = float(c.z) if c.z is not None else default_z
        station = float(line.project(Point(px, py))) if line is not None else 0.0
        ports.append(
            Port(
                key=f"{elem_id}:{port_id}",
                element_id=elem_id,
                port_id=port_id,
                domain=c.domain,
                classification=c.classification,
                shape=c.shape,
                direction=c.direction,
                x=px,
                y=py,
                z=pz,
                z_explicit=c.z is not None,
                story=c.story or default_story,
                width=float(c.width) if c.width is not None else None,
                height=float(c.height) if c.height is not None else None,
                diameter=float(c.diameter) if c.diameter is not None else None,
                flow=float(c.flow) if c.flow is not None else None,
                fixture_units=float(c.fixtureUnits) if c.fixtureUnits is not None else None,
                load=float(c.load) if c.load is not None else None,
                circuit=c.circuit,
                system_name=c.systemName,
                connected_to=c.connectedTo,
                station=station,
                derived=False,
            )
        )
    return ports


def _collect_elements(mep: MepModel, building: Any = None) -> list[ElementNode]:
    """Extracts all MEP elements and resolves or derives their connectors."""
    levels, order, soffits = _story_levels(mep, building)
    elements: list[ElementNode] = []

    # Equipment from coordination section linked by a service item is represented once by the service.
    linked_equip: set[str] = set()
    for group in (
        mep.hvac.plant if mep.hvac else [],
        mep.electrical.equipment if mep.electrical else [],
        mep.fire.pumps if mep.fire else [],
        mep.plumbing.tanks if mep.plumbing else [],
    ):
        for item in group:
            if getattr(item, "equipment", None):
                linked_equip.add(str(item.equipment))

    for eq in mep.equipment:
        if eq.id in linked_equip:
            continue
        domain, cls, direction, is_source = _EQUIP_ROLE.get(
            eq.kind, ("electrical", "power", "in", False)
        )
        z = levels.get(eq.story, 0.0) + float(eq.height or 0.0) / 2.0
        node = ElementNode(
            id=eq.id,
            kind=eq.kind,
            discipline="coordination",
            story=eq.story,
            domain=domain,
            classification=cls,
            is_source=is_source,
            footprint=_footprint_of(eq),
            equipment_kind=eq.kind,
            has_explicit_connectors=bool(eq.connectors),
        )
        if eq.connectors:
            node.ports = _explicit_ports(eq, eq.id, float(eq.x), float(eq.y), z, eq.story)
            node.domain = node.ports[0].domain
            node.classification = node.ports[0].classification
        else:
            node.ports = [
                Port(
                    key=f"{eq.id}:C1",
                    element_id=eq.id,
                    port_id="C1",
                    domain=domain,
                    classification=cls,
                    shape="rect" if domain == "duct" else "round" if domain == "pipe" else "point",
                    direction=direction,
                    x=float(eq.x),
                    y=float(eq.y),
                    z=z,
                    z_explicit=False,
                    story=eq.story,
                    derived=True,
                )
            ]
        elements.append(node)

    if mep.hvac is not None:
        _collect_hvac(mep.hvac, levels, order, soffits, elements)
    if mep.plumbing is not None:
        _collect_plumbing(mep.plumbing, levels, order, soffits, elements)
    if mep.fire is not None:
        _collect_fire(mep.fire, levels, order, soffits, elements)
    if mep.electrical is not None:
        _collect_electrical(mep.electrical, levels, order, soffits, elements)

    return elements


def _collect_hvac(
    hvac: Any,
    levels: dict[str, float],
    order: list[str],
    soffits: dict[str, float],
    elements: list[ElementNode],
) -> None:
    for plant in hvac.plant:
        domain, cls, direction, is_source = _EQUIP_ROLE.get(
            plant.kind, ("duct", "supplyAir", "out", True)
        )
        z = levels.get(plant.story, 0.0) + float(plant.height or 0.0) / 2.0
        cap_lps = (
            float(plant.capacity) * 1000.0
            if plant.capacity is not None and plant.kind in ("exhaustFan", "freshAirUnit")
            else None
        )
        node = ElementNode(
            id=plant.id,
            kind=plant.kind,
            discipline="hvac",
            story=plant.story,
            domain=domain,
            classification=cls,
            is_source=is_source,
            footprint=_footprint_of(plant),
            capacity=float(plant.capacity) if plant.capacity is not None else None,
            flow=cap_lps,
            load=float(plant.power) if plant.power is not None else None,
            has_explicit_connectors=bool(plant.connectors),
            equipment_kind=plant.kind,
            serves=list(plant.serves) if plant.serves else None,
        )
        if plant.connectors:
            node.ports = _explicit_ports(
                plant, plant.id, float(plant.x), float(plant.y), z, plant.story
            )
            node.domain = node.ports[0].domain
            node.classification = node.ports[0].classification
        else:
            node.ports = [
                Port(
                    key=f"{plant.id}:C1",
                    element_id=plant.id,
                    port_id="C1",
                    domain=domain,
                    classification=cls,
                    shape="rect" if domain == "duct" else "round",
                    direction=direction,
                    x=float(plant.x),
                    y=float(plant.y),
                    z=z,
                    z_explicit=False,
                    story=plant.story,
                    flow=cap_lps,
                    derived=True,
                )
            ]
        elements.append(node)

    for duct in hvac.ducts:
        cls = _DUCT_TO_CLASS.get(duct.system, "supplyAir")
        height = float(duct.diameter or duct.height or 250.0)
        flow_lps = float(duct.flow) * 1000.0 if duct.flow is not None else None
        if duct.riser is not None:
            low = levels.get(duct.riser.fromStory, 0.0)
            high = levels.get(duct.riser.toStory, low + 3200.0)
            px, py = float(duct.path[0][0]), float(duct.path[0][1])
            passed = _stories_between(order, levels, duct.riser.fromStory, duct.riser.toStory)
            node = ElementNode(
                id=duct.id,
                kind="ductRiser",
                discipline="hvac",
                story=duct.riser.fromStory,
                domain="duct",
                classification=cls,
                is_run=True,
                is_riser=True,
                path=[(px, py)],
                z_low=min(low, high),
                z_high=max(low, high),
                stories_passed=passed,
                flow=flow_lps,
                has_explicit_connectors=bool(duct.connectors),
            )
            if duct.connectors:
                node.ports = _explicit_ports(duct, duct.id, px, py, low, duct.riser.fromStory)
            else:
                node.ports = [
                    _run_port(
                        duct.id, "bottom", "duct", cls, duct.shape, "bidirectional",
                        px, py, min(low, high), True, duct.riser.fromStory,
                        duct.width, duct.height, duct.diameter, 0.0,
                    ),
                    _run_port(
                        duct.id, "top", "duct", cls, duct.shape, "bidirectional",
                        px, py, max(low, high), True, duct.riser.toStory,
                        duct.width, duct.height, duct.diameter, abs(high - low),
                    ),
                ]  # fmt: skip
            elements.append(node)
            continue

        pts = [(float(p[0]), float(p[1])) for p in duct.path]
        z, z_exp = _run_z(duct.story, duct.bottom, height, _DUCT_HANGER, levels, soffits)
        node = ElementNode(
            id=duct.id,
            kind="duct",
            discipline="hvac",
            story=duct.story,
            domain="duct",
            classification=cls,
            is_run=True,
            path=pts,
            run_z=z,
            flow=flow_lps,
            has_explicit_connectors=bool(duct.connectors),
        )
        if duct.connectors:
            node.ports = _explicit_ports(
                duct, duct.id, pts[0][0], pts[0][1], z, duct.story, path=pts
            )
        elif len(pts) >= 2:
            total_len = path_length(pts)
            node.ports = [
                _run_port(
                    duct.id, "start", "duct", cls, duct.shape, "bidirectional",
                    pts[0][0], pts[0][1], z, z_exp, duct.story,
                    duct.width, duct.height, duct.diameter, 0.0,
                ),
                _run_port(
                    duct.id, "end", "duct", cls, duct.shape, "bidirectional",
                    pts[-1][0], pts[-1][1], z, z_exp, duct.story,
                    duct.width, duct.height, duct.diameter, total_len,
                ),
            ]  # fmt: skip
        else:
            node.ports = [
                _run_port(
                    duct.id,
                    "C1",
                    "duct",
                    cls,
                    duct.shape,
                    "bidirectional",
                    pts[0][0],
                    pts[0][1],
                    z,
                    z_exp,
                    duct.story,
                    duct.width,
                    duct.height,
                    duct.diameter,
                    0.0,
                )
            ]
        elements.append(node)

    for term in hvac.terminals:
        cls = _DUCT_TO_CLASS.get(term.system, "supplyAir")
        direction = "in" if term.kind == "supplyDiffuser" else "out"
        shape = "round" if term.diameter is not None else "rect"
        height = float(term.diameter or term.height or 250.0)
        default_z, _ = _run_z(term.story, None, height, _DUCT_HANGER, levels, soffits)
        z = float(term.z) if term.z is not None else default_z
        node = ElementNode(
            id=term.id,
            kind=term.kind,
            discipline="hvac",
            story=term.story,
            domain="duct",
            classification=cls,
            is_terminal=True,
            flow=float(term.flow) if term.flow is not None else None,
            has_explicit_connectors=bool(term.connectors),
        )
        if term.connectors:
            node.ports = _explicit_ports(term, term.id, float(term.x), float(term.y), z, term.story)
        else:
            node.ports = [
                Port(
                    key=f"{term.id}:C1",
                    element_id=term.id,
                    port_id="C1",
                    domain="duct",
                    classification=cls,
                    shape=shape,
                    direction=direction,
                    x=float(term.x),
                    y=float(term.y),
                    z=z,
                    z_explicit=term.z is not None,
                    story=term.story,
                    width=float(term.width) if term.width is not None else None,
                    height=float(term.height) if term.height is not None else None,
                    diameter=float(term.diameter) if term.diameter is not None else None,
                    flow=float(term.flow) if term.flow is not None else None,
                    derived=True,
                )
            ]
        elements.append(node)

    for pipe in hvac.pipes:
        elements.append(_pipe_node(pipe, "hvac", levels, soffits))


def _pipe_node(
    pipe: Any, discipline: str, levels: dict[str, float], soffits: dict[str, float]
) -> ElementNode:
    cls = _PLUMBING_TO_CLASS.get(pipe.system, "domesticColdWater")
    pts = [(float(p[0]), float(p[1])) for p in pipe.path]
    diam = float(pipe.diameter) if pipe.diameter is not None else None
    z, z_exp = _run_z(pipe.story, pipe.bottom, diam or 50.0, _TRAY_HEADROOM, levels, soffits)
    node = ElementNode(
        id=pipe.id,
        kind="pipe",
        discipline=discipline,
        story=pipe.story,
        domain="pipe",
        classification=cls,
        is_run=True,
        path=pts,
        run_z=z,
        flow=float(pipe.flow) if pipe.flow is not None else None,
        fixture_units=float(pipe.fixtureUnits) if pipe.fixtureUnits is not None else None,
        has_explicit_connectors=bool(pipe.connectors),
    )
    if pipe.connectors:
        node.ports = _explicit_ports(pipe, pipe.id, pts[0][0], pts[0][1], z, pipe.story, path=pts)
    else:
        total_len = path_length(pts)
        node.ports = [
            _run_port(
                pipe.id, "start", "pipe", cls, "round", "bidirectional",
                pts[0][0], pts[0][1], z, z_exp, pipe.story,
                None, None, diam, 0.0,
            ),
            _run_port(
                pipe.id, "end", "pipe", cls, "round", "bidirectional",
                pts[-1][0], pts[-1][1], z, z_exp, pipe.story,
                None, None, diam, total_len,
            ),
        ]  # fmt: skip
    return node


def _collect_plumbing(
    plumbing: Any,
    levels: dict[str, float],
    order: list[str],
    soffits: dict[str, float],
    elements: list[ElementNode],
) -> None:
    for tank in plumbing.tanks:
        is_drainage = tank.kind in ("septic", "soakWell")
        cls = "sanitary" if is_drainage else "domesticColdWater"
        direction = "in" if is_drainage else "out"
        story = tank.story or (order[0] if order else None)
        z = levels.get(story or "", 0.0)
        node = ElementNode(
            id=tank.id,
            kind=f"tank:{tank.kind}",
            discipline="plumbing",
            story=story,
            domain="pipe",
            classification=cls,
            is_source=True,
            footprint=_footprint_of(tank),
            has_explicit_connectors=bool(tank.connectors),
        )
        if tank.connectors:
            node.ports = _explicit_ports(tank, tank.id, float(tank.x), float(tank.y), z, story)
        else:
            node.ports = [
                Port(
                    key=f"{tank.id}:C1",
                    element_id=tank.id,
                    port_id="C1",
                    domain="pipe",
                    classification=cls,
                    shape="round",
                    direction=direction,
                    x=float(tank.x),
                    y=float(tank.y),
                    z=z,
                    z_explicit=False,
                    story=story,
                    derived=True,
                )
            ]
        elements.append(node)

    for riser in plumbing.risers:
        cls = _PLUMBING_TO_CLASS.get(riser.system, "domesticColdWater")
        low = levels.get(riser.fromStory, 0.0)
        high = levels.get(riser.toStory, low + 3200.0)
        passed = _stories_between(order, levels, riser.fromStory, riser.toStory)
        diam = float(riser.diameter) if riser.diameter is not None else None
        node = ElementNode(
            id=riser.id,
            kind="riser",
            discipline="plumbing",
            story=riser.fromStory,
            domain="pipe",
            classification=cls,
            is_run=True,
            is_riser=True,
            path=[(float(riser.x), float(riser.y))],
            z_low=min(low, high),
            z_high=max(low, high),
            stories_passed=passed,
            serves=list(riser.serves) if riser.serves else None,
            has_explicit_connectors=bool(riser.connectors),
        )
        if riser.connectors:
            node.ports = _explicit_ports(
                riser, riser.id, float(riser.x), float(riser.y), low, riser.fromStory
            )
        else:
            node.ports = [
                _run_port(
                    riser.id, "bottom", "pipe", cls, "round", "bidirectional",
                    float(riser.x), float(riser.y), min(low, high), True, riser.fromStory,
                    None, None, diam, 0.0,
                ),
                _run_port(
                    riser.id, "top", "pipe", cls, "round", "bidirectional",
                    float(riser.x), float(riser.y), max(low, high), True, riser.toStory,
                    None, None, diam, abs(high - low),
                ),
            ]  # fmt: skip
        elements.append(node)

    for pipe in plumbing.pipes:
        elements.append(_pipe_node(pipe, "plumbing", levels, soffits))

    for drain in plumbing.roof.drains if plumbing.roof else []:
        z = levels.get(drain.story, 0.0)
        node = ElementNode(
            id=drain.id,
            kind="roofDrain",
            discipline="plumbing",
            story=drain.story,
            domain="pipe",
            classification="stormWater",
            is_source=True,
            is_terminal=True,
            has_explicit_connectors=bool(drain.connectors),
        )
        if drain.connectors:
            node.ports = _explicit_ports(
                drain, drain.id, float(drain.x), float(drain.y), z, drain.story
            )
        else:
            node.ports = [
                Port(
                    key=f"{drain.id}:C1",
                    element_id=drain.id,
                    port_id="C1",
                    domain="pipe",
                    classification="stormWater",
                    shape="round",
                    direction="out",
                    x=float(drain.x),
                    y=float(drain.y),
                    z=z,
                    z_explicit=False,
                    story=drain.story,
                    derived=True,
                )
            ]
        elements.append(node)


def _collect_fire(
    fire: Any,
    levels: dict[str, float],
    order: list[str],
    soffits: dict[str, float],
    elements: list[ElementNode],
) -> None:
    for tank in fire.tanks:
        story = tank.story or (order[0] if order else None)
        z = levels.get(story or "", 0.0)
        node = ElementNode(
            id=tank.id,
            kind=f"fireTank:{tank.kind}",
            discipline="fire",
            story=story,
            domain="pipe",
            classification="fireProtection",
            is_source=True,
            footprint=_footprint_of(tank),
            has_explicit_connectors=bool(tank.connectors),
        )
        if tank.connectors:
            node.ports = _explicit_ports(tank, tank.id, float(tank.x), float(tank.y), z, story)
        else:
            node.ports = [
                Port(
                    key=f"{tank.id}:C1",
                    element_id=tank.id,
                    port_id="C1",
                    domain="pipe",
                    classification="fireProtection",
                    shape="round",
                    direction="out",
                    x=float(tank.x),
                    y=float(tank.y),
                    z=z,
                    z_explicit=False,
                    story=story,
                    derived=True,
                )
            ]
        elements.append(node)

    for pump in fire.pumps:
        z = levels.get(pump.story, 0.0)
        flow_lps = float(pump.flow) / 60.0 if pump.flow is not None else None
        node = ElementNode(
            id=pump.id,
            kind="firePump",
            discipline="fire",
            story=pump.story,
            domain="pipe",
            classification="fireProtection",
            is_source=True,
            footprint=_footprint_of(pump),
            flow=flow_lps,
            load=float(pump.power) if pump.power is not None else None,
            has_explicit_connectors=bool(pump.connectors),
        )
        if pump.connectors:
            node.ports = _explicit_ports(pump, pump.id, float(pump.x), float(pump.y), z, pump.story)
        else:
            node.ports = [
                Port(
                    key=f"{pump.id}:C1",
                    element_id=pump.id,
                    port_id="C1",
                    domain="pipe",
                    classification="fireProtection",
                    shape="round",
                    direction="out",
                    x=float(pump.x),
                    y=float(pump.y),
                    z=z,
                    z_explicit=False,
                    story=pump.story,
                    flow=flow_lps,
                    derived=True,
                )
            ]
        elements.append(node)

    for riser in fire.risers:
        low = levels.get(riser.fromStory, 0.0)
        high = levels.get(riser.toStory, low + 3200.0)
        passed = _stories_between(order, levels, riser.fromStory, riser.toStory)
        diam = float(riser.diameter) if riser.diameter is not None else None
        node = ElementNode(
            id=riser.id,
            kind=f"fireRiser:{riser.system}",
            discipline="fire",
            story=riser.fromStory,
            domain="pipe",
            classification="fireProtection",
            is_run=True,
            is_riser=True,
            path=[(float(riser.x), float(riser.y))],
            z_low=min(low, high),
            z_high=max(low, high),
            stories_passed=passed,
            has_explicit_connectors=bool(riser.connectors),
        )
        if riser.connectors:
            node.ports = _explicit_ports(
                riser, riser.id, float(riser.x), float(riser.y), low, riser.fromStory
            )
        else:
            node.ports = [
                _run_port(
                    riser.id, "bottom", "pipe", "fireProtection", "round", "bidirectional",
                    float(riser.x), float(riser.y), min(low, high), True, riser.fromStory,
                    None, None, diam, 0.0,
                ),
                _run_port(
                    riser.id, "top", "pipe", "fireProtection", "round", "bidirectional",
                    float(riser.x), float(riser.y), max(low, high), True, riser.toStory,
                    None, None, diam, abs(high - low),
                ),
            ]  # fmt: skip
        elements.append(node)

    for main in fire.mains:
        pts = [(float(p[0]), float(p[1])) for p in main.path]
        diam = float(main.diameter) if main.diameter is not None else None
        z, z_exp = _run_z(main.story, main.bottom, diam or 100.0, _TRAY_HEADROOM, levels, soffits)
        node = ElementNode(
            id=main.id,
            kind="fireMain",
            discipline="fire",
            story=main.story,
            domain="pipe",
            classification="fireProtection",
            is_run=True,
            path=pts,
            run_z=z,
            has_explicit_connectors=bool(main.connectors),
        )
        if main.connectors:
            node.ports = _explicit_ports(
                main, main.id, pts[0][0], pts[0][1], z, main.story, path=pts
            )
        else:
            total_len = path_length(pts)
            node.ports = [
                _run_port(
                    main.id, "start", "pipe", "fireProtection", "round", "bidirectional",
                    pts[0][0], pts[0][1], z, z_exp, main.story,
                    None, None, diam, 0.0,
                ),
                _run_port(
                    main.id, "end", "pipe", "fireProtection", "round", "bidirectional",
                    pts[-1][0], pts[-1][1], z, z_exp, main.story,
                    None, None, diam, total_len,
                ),
            ]  # fmt: skip
        elements.append(node)

    for sp in getattr(fire, "sprinklerPipes", []) or []:
        pts = [(float(p[0]), float(p[1])) for p in sp.path]
        diam = float(sp.diameter) if sp.diameter is not None else None
        z, z_exp = _run_z(sp.story, sp.bottom, diam or 25.0, _TRAY_HEADROOM, levels, soffits)
        node = ElementNode(
            id=sp.id,
            kind=f"sprinklerPipe:{sp.kind}",
            discipline="fire",
            story=sp.story,
            domain="pipe",
            classification="fireProtection",
            is_run=True,
            path=pts,
            run_z=z,
            has_explicit_connectors=bool(sp.connectors),
        )
        if sp.connectors:
            node.ports = _explicit_ports(sp, sp.id, pts[0][0], pts[0][1], z, sp.story, path=pts)
        else:
            total_len = path_length(pts)
            node.ports = [
                _run_port(
                    sp.id, "start", "pipe", "fireProtection", "round", "bidirectional",
                    pts[0][0], pts[0][1], z, z_exp, sp.story,
                    None, None, diam, 0.0,
                ),
                _run_port(
                    sp.id, "end", "pipe", "fireProtection", "round", "bidirectional",
                    pts[-1][0], pts[-1][1], z, z_exp, sp.story,
                    None, None, diam, total_len,
                ),
            ]  # fmt: skip
        elements.append(node)

    for sh in getattr(fire, "sprinklerHeads", []) or []:
        default_z, _ = _run_z(sh.story, None, 80.0, _TRAY_HEADROOM, levels, soffits)
        z = float(sh.z) if sh.z is not None else default_z
        node = ElementNode(
            id=sh.id,
            kind="sprinklerHead",
            discipline="fire",
            story=sh.story,
            domain="pipe",
            classification="fireProtection",
            is_terminal=True,
            has_explicit_connectors=bool(sh.connectors),
        )
        if sh.connectors:
            node.ports = _explicit_ports(sh, sh.id, float(sh.x), float(sh.y), z, sh.story)
        else:
            node.ports = [
                Port(
                    key=f"{sh.id}:C1",
                    element_id=sh.id,
                    port_id="C1",
                    domain="pipe",
                    classification="fireProtection",
                    shape="round",
                    direction="in",
                    x=float(sh.x),
                    y=float(sh.y),
                    z=z,
                    z_explicit=sh.z is not None,
                    story=sh.story,
                    derived=True,
                )
            ]
        elements.append(node)


def _collect_electrical(
    electrical: Any,
    levels: dict[str, float],
    order: list[str],
    soffits: dict[str, float],
    elements: list[ElementNode],
) -> None:
    for eq in electrical.equipment:
        domain, cls, direction, is_source = _EQUIP_ROLE.get(
            eq.kind, ("electrical", "power", "out", True)
        )
        z = levels.get(eq.story, 0.0) + float(eq.height or 0.0) / 2.0
        node = ElementNode(
            id=eq.id,
            kind=eq.kind,
            discipline="electrical",
            story=eq.story,
            domain=domain,
            classification=cls,
            is_source=is_source,
            footprint=_footprint_of(eq),
            equipment_kind=eq.kind,
            has_explicit_connectors=bool(eq.connectors),
        )
        if eq.connectors:
            node.ports = _explicit_ports(eq, eq.id, float(eq.x), float(eq.y), z, eq.story)
            node.domain = node.ports[0].domain
            node.classification = node.ports[0].classification
        else:
            node.ports = [
                Port(
                    key=f"{eq.id}:C1",
                    element_id=eq.id,
                    port_id="C1",
                    domain=domain,
                    classification=cls,
                    shape="point",
                    direction=direction,
                    x=float(eq.x),
                    y=float(eq.y),
                    z=z,
                    z_explicit=False,
                    story=eq.story,
                    derived=True,
                )
            ]
        elements.append(node)

    for riser in electrical.risers:
        domain = "electrical" if riser.kind == "busbar" else "cableTray"
        cls = "power" if riser.kind == "busbar" else "cableTray"
        low = levels.get(riser.fromStory, 0.0)
        high = levels.get(riser.toStory, low + 3200.0)
        passed = _stories_between(order, levels, riser.fromStory, riser.toStory)
        node = ElementNode(
            id=riser.id,
            kind=f"elecRiser:{riser.kind}",
            discipline="electrical",
            story=riser.fromStory,
            domain=domain,
            classification=cls,
            is_run=True,
            is_riser=True,
            path=[(float(riser.x), float(riser.y))],
            z_low=min(low, high),
            z_high=max(low, high),
            stories_passed=passed,
            serves=list(riser.serves) if riser.serves else None,
            has_explicit_connectors=bool(riser.connectors),
        )
        if riser.connectors:
            node.ports = _explicit_ports(
                riser, riser.id, float(riser.x), float(riser.y), low, riser.fromStory
            )
        else:
            node.ports = [
                _run_port(
                    riser.id, "bottom", domain, cls, "rect", "bidirectional",
                    float(riser.x), float(riser.y), min(low, high), True, riser.fromStory,
                    riser.width, riser.depth, None, 0.0,
                ),
                _run_port(
                    riser.id, "top", domain, cls, "rect", "bidirectional",
                    float(riser.x), float(riser.y), max(low, high), True, riser.toStory,
                    riser.width, riser.depth, None, abs(high - low),
                ),
            ]  # fmt: skip
        elements.append(node)

    for tray in electrical.trays:
        pts = [(float(p[0]), float(p[1])) for p in tray.path]
        z, z_exp = _run_z(
            tray.story, tray.bottom, float(tray.height), _TRAY_HEADROOM, levels, soffits
        )
        node = ElementNode(
            id=tray.id,
            kind="cableTray",
            discipline="electrical",
            story=tray.story,
            domain="cableTray",
            classification="cableTray",
            is_run=True,
            path=pts,
            run_z=z,
            has_explicit_connectors=bool(tray.connectors),
        )
        if tray.connectors:
            node.ports = _explicit_ports(
                tray, tray.id, pts[0][0], pts[0][1], z, tray.story, path=pts
            )
        else:
            total_len = path_length(pts)
            node.ports = [
                _run_port(
                    tray.id, "start", "cableTray", "cableTray", "rect", "bidirectional",
                    pts[0][0], pts[0][1], z, z_exp, tray.story,
                    float(tray.width), float(tray.height), None, 0.0,
                ),
                _run_port(
                    tray.id, "end", "cableTray", "cableTray", "rect", "bidirectional",
                    pts[-1][0], pts[-1][1], z, z_exp, tray.story,
                    float(tray.width), float(tray.height), None, total_len,
                ),
            ]  # fmt: skip
        elements.append(node)

    for motor in electrical.motors:
        if (motor.x is None or motor.y is None) and not motor.connectors:
            continue
        story = motor.story or (order[0] if order else None)
        z = levels.get(story or "", 0.0)
        load_kw = float(motor.power) * int(motor.count)
        mx = float(motor.x or 0.0)
        my = float(motor.y or 0.0)
        node = ElementNode(
            id=motor.id,
            kind=f"motor:{motor.kind}",
            discipline="electrical",
            story=story,
            domain="electrical",
            classification="power",
            is_terminal=True,
            load=load_kw,
            has_explicit_connectors=bool(motor.connectors),
        )
        if motor.connectors:
            node.ports = _explicit_ports(motor, motor.id, mx, my, z, story)
        else:
            node.ports = [
                Port(
                    key=f"{motor.id}:C1",
                    element_id=motor.id,
                    port_id="C1",
                    domain="electrical",
                    classification="power",
                    shape="point",
                    direction="in",
                    x=mx,
                    y=my,
                    z=z,
                    z_explicit=False,
                    story=story,
                    load=load_kw,
                    derived=True,
                )
            ]
        elements.append(node)


def _run_port(
    elem_id: str,
    port_id: str,
    domain: str,
    classification: str,
    shape: str,
    direction: str,
    x: float,
    y: float,
    z: float,
    z_explicit: bool,
    story: str | None,
    width: float | None,
    height: float | None,
    diameter: float | None,
    station: float,
) -> Port:
    return Port(
        key=f"{elem_id}:{port_id}",
        element_id=elem_id,
        port_id=port_id,
        domain=domain,
        classification=classification,
        shape=shape,
        direction=direction,
        x=x,
        y=y,
        z=z,
        z_explicit=z_explicit,
        story=story,
        width=float(width) if width is not None else None,
        height=float(height) if height is not None else None,
        diameter=float(diameter) if diameter is not None else None,
        station=station,
        derived=True,
    )


def _ports_coincide(a: Port, b: Port, tol: float) -> bool:
    if math.hypot(a.x - b.x, a.y - b.y) > tol:
        return False
    if a.z_explicit and b.z_explicit:
        return abs(a.z - b.z) <= tol
    if a.story and b.story:
        return a.story == b.story or abs(a.z - b.z) <= tol
    return abs(a.z - b.z) <= tol


def _compatible_z(port: Port, node: ElementNode, tol: float) -> bool:
    if node.is_riser:
        if port.story and node.stories_passed and port.story in node.stories_passed:
            return True
        if node.z_low is not None and node.z_high is not None:
            return node.z_low - tol <= port.z <= node.z_high + tol
        return False
    if port.z_explicit and node.run_z is not None:
        return abs(port.z - node.run_z) <= tol
    if port.story and node.story:
        return port.story == node.story
    return node.run_z is None or abs(port.z - node.run_z) <= tol


def _snap_connections(
    elements: list[ElementNode], tolerance: float
) -> tuple[list[Connection], set[str]]:
    """Connects coinciding ports, T-taps, riser taps and equipment footprints."""
    by_id = {e.id: e for e in elements}
    all_ports: list[Port] = [p for e in elements for p in e.ports]
    port_by_key = {p.key: p for p in all_ports}
    connections: list[Connection] = []
    connected_keys: set[str] = set()
    pair_seen: set[tuple[str, str]] = set()

    def link(a: Port, b: Port, is_tee: bool = False) -> None:
        if a.element_id == b.element_id:
            return
        pair = (a.key, b.key) if a.key <= b.key else (b.key, a.key)
        if pair in pair_seen:
            return
        pair_seen.add(pair)
        connections.append(Connection(a, b, is_tee=is_tee))
        connected_keys.add(a.key)
        connected_keys.add(b.key)

    # 1. Explicit connectedTo references.
    for port in all_ports:
        if not port.connected_to:
            continue
        target_port = port_by_key.get(port.connected_to)
        if target_port is None and ":" not in port.connected_to:
            target_elem = by_id.get(port.connected_to)
            if target_elem and target_elem.ports:
                target_port = next(
                    (p for p in target_elem.ports if p.classification == port.classification),
                    target_elem.ports[0],
                )
        if target_port is not None:
            link(port, target_port, is_tee=False)

    # 2. Point-to-point snap in the same domain.
    for a, b in itertools.combinations(all_ports, 2):
        if a.element_id == b.element_id or a.domain != b.domain:
            continue
        if _ports_coincide(a, b, tolerance):
            link(a, b, is_tee=False)

    # 3. T-tap: unconnected run/terminal endpoint landing on another run's segment.
    runs = [e for e in elements if e.is_run and not e.is_riser and len(e.path) >= 2]
    run_lines = {e.id: LineString(e.path) for e in runs}
    tee_counter: dict[str, int] = {}

    for port in list(all_ports):
        if port.key in connected_keys:
            continue
        src_node = by_id[port.element_id]
        if not (src_node.is_run or src_node.is_terminal):
            continue
        pt = Point(port.x, port.y)
        for host in runs:
            if host.id == port.element_id or host.domain != port.domain:
                continue
            if not _compatible_z(port, host, tolerance):
                continue
            line = run_lines[host.id]
            if line.distance(pt) > tolerance:
                continue
            proj = float(line.project(pt))
            if any(math.hypot(port.x - hp.x, port.y - hp.y) <= tolerance for hp in host.ports):
                continue
            tee_counter[host.id] = tee_counter.get(host.id, 0) + 1
            tee_id = f"T{tee_counter[host.id]}"
            nearest = line.interpolate(proj)
            ref = host.ports[0] if host.ports else None
            tee_port = _run_port(
                host.id,
                tee_id,
                host.domain,
                host.classification,
                ref.shape if ref else "rect",
                "bidirectional",
                float(nearest.x),
                float(nearest.y),
                host.run_z if host.run_z is not None else port.z,
                False,
                host.story,
                ref.width if ref else None,
                ref.height if ref else None,
                ref.diameter if ref else None,
                proj,
            )
            host.ports.append(tee_port)
            port_by_key[tee_port.key] = tee_port
            link(port, tee_port, is_tee=True)
            break

    # 4. Vertical riser tap: unconnected horizontal run endpoint near a riser shaft.
    risers = [e for e in elements if e.is_riser and e.path]
    for port in list(all_ports):
        if port.key in connected_keys:
            continue
        for riser in risers:
            if riser.id == port.element_id or riser.domain != port.domain:
                continue
            rx, ry = riser.path[0]
            if math.hypot(port.x - rx, port.y - ry) > tolerance:
                continue
            if not _compatible_z(port, riser, tolerance):
                continue
            tee_counter[riser.id] = tee_counter.get(riser.id, 0) + 1
            tee_id = f"T{tee_counter[riser.id]}"
            ref = riser.ports[0] if riser.ports else None
            tee_port = _run_port(
                riser.id,
                tee_id,
                riser.domain,
                riser.classification,
                ref.shape if ref else "round",
                "bidirectional",
                rx,
                ry,
                port.z,
                True,
                port.story or riser.story,
                ref.width if ref else None,
                ref.height if ref else None,
                ref.diameter if ref else None,
                abs(port.z - (riser.z_low or 0.0)),
            )
            riser.ports.append(tee_port)
            port_by_key[tee_port.key] = tee_port
            link(port, tee_port, is_tee=True)
            break

    # 5. Footprint snap onto equipment/plant/tanks without explicit connectors.
    equip_nodes = [
        e
        for e in elements
        if not e.is_run and not e.is_terminal and e.footprint and not e.has_explicit_connectors
    ]
    for port in list(all_ports):
        if port.key in connected_keys:
            continue
        for eq in equip_nodes:
            if eq.id == port.element_id:
                continue
            if eq.story and port.story and eq.story != port.story:
                continue
            assert eq.footprint is not None
            if not inside((port.x, port.y), eq.footprint, tol=tolerance):
                continue
            accepted = _MULTI_PORT_HVAC_ACCEPT.get(eq.equipment_kind, ())
            if port.classification in accepted:
                target = next(
                    (p for p in eq.ports if p.classification == port.classification), None
                )
                if target is None:
                    direction = "in" if port.classification == "returnAir" else "out"
                    target = Port(
                        key=f"{eq.id}:C{len(eq.ports) + 1}",
                        element_id=eq.id,
                        port_id=f"C{len(eq.ports) + 1}",
                        domain=port.domain,
                        classification=port.classification,
                        shape=port.shape,
                        direction=direction,
                        x=port.x,
                        y=port.y,
                        z=port.z,
                        z_explicit=False,
                        story=eq.story,
                        derived=True,
                    )
                    eq.ports.append(target)
                    port_by_key[target.key] = target
                link(port, target, is_tee=False)
                break
            if eq.domain == port.domain and eq.ports:
                link(port, eq.ports[0], is_tee=False)
                break

    return connections, connected_keys


def _size_mismatch_detail(a: Port, b: Port) -> str | None:
    """Returns mismatch description if both ports have explicit incompatible sizes, else None."""
    has_a = a.diameter is not None or (a.width is not None and a.height is not None)
    has_b = b.diameter is not None or (b.width is not None and b.height is not None)
    if not (has_a and has_b):
        return None
    if a.shape == "round" and b.shape == "round":
        if (
            a.diameter is not None
            and b.diameter is not None
            and abs(a.diameter - b.diameter) > SIZE_TOLERANCE
        ):
            return f"{a.diameter:g} mm vs {b.diameter:g} mm"
        return None
    if a.shape == "rect" and b.shape == "rect":
        if (
            a.width is not None
            and b.width is not None
            and a.height is not None
            and b.height is not None
            and (
                abs(a.width - b.width) > SIZE_TOLERANCE or abs(a.height - b.height) > SIZE_TOLERANCE
            )
        ):
            return f"{a.width:g}×{a.height:g} mm vs {b.width:g}×{b.height:g} mm"
        return None
    if a.shape != b.shape and "point" not in (a.shape, b.shape):
        return f"{a.shape} ({a.size_label}) vs {b.shape} ({b.size_label})"
    return None


def _direction_conflict(a: Port, b: Port) -> bool:
    return (a.direction == "out" and b.direction == "out") or (
        a.direction == "in" and b.direction == "in"
    )


def _critical_path(
    start_ports: list[Port],
    nodes_by_id: dict[str, ElementNode],
    adj_ports: dict[str, list[tuple[str, float]]],
) -> tuple[float, list[str]]:
    """Weighted shortest-path distance from source port(s) to the furthest reachable port."""
    if not start_ports:
        return 0.0, []
    dist: dict[str, float] = {}
    prev: dict[str, str | None] = {}
    heap: list[tuple[float, str]] = []
    for sp in start_ports:
        dist[sp.key] = 0.0
        prev[sp.key] = None
        heapq.heappush(heap, (0.0, sp.key))

    while heap:
        d, u = heapq.heappop(heap)
        if d > dist.get(u, math.inf):
            continue
        for v, w in adj_ports.get(u, []):
            nd = d + w
            if nd < dist.get(v, math.inf) - 1e-9:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))

    if not dist:
        return 0.0, []
    furthest = max(
        dist,
        key=lambda k: (
            round(dist[k], 6),
            1 if nodes_by_id[k.split(":", 1)[0]].is_terminal else 0,
        ),
    )
    max_len = dist[furthest]
    chain: list[str] = []
    cur: str | None = furthest
    while cur is not None:
        eid = cur.split(":", 1)[0]
        if not chain or chain[-1] != eid:
            chain.append(eid)
        cur = prev.get(cur)
    chain.reverse()
    return round(max_len, 3), chain


def _existing_air_flows(mep: MepModel, building: Any) -> dict[str, float]:
    """Reuses :mod:`saengine.hvac.air` to derive airflows [l/s] when ducts omit explicit flow."""
    if mep.hvac is None or not mep.hvac.ducts:
        return {}
    try:
        from saengine.hvac.air import Project as AirProject
        from saengine.hvac.air import duct_flows, hvac_section, zone_air
        from saengine.plumbing.building import Building

        b = Building.of(building)
        proj = AirProject(Path("."), mep, hvac_section(mep, None), bim=building, building=b)
        if not proj.hvac.get("stories"):
            return {}
        zones, _ = zone_air(
            proj, {"zones": [{"story": s.get("story")} for s in proj.hvac.get("stories", [])]}
        )
        flows, _ = duct_flows(proj, zones)
        return {k: v * 1000.0 for k, v in flows.items()}
    except Exception:  # noqa: BLE001 - optional fallback when building context is incomplete
        return {}


def _system_totals(
    classification: str,
    elem_ids: list[str],
    parent_elem: dict[str, str | None],
    nodes_by_id: dict[str, ElementNode],
    mep: MepModel,
    building: Any,
    air_flows_cache: dict[str, float] | None = None,
) -> dict[str, float | None]:
    """Computes per-system totals reusing existing HVAC, plumbing and electrical calculations."""
    member_set = set(elem_ids)
    # Leaf elements in the BFS spanning tree (no child elements inside the system).
    has_child = {parent_elem[eid] for eid in elem_ids if parent_elem.get(eid) in member_set}
    leaves = [eid for eid in elem_ids if eid not in has_child]

    air_flow: float | None = None
    water_flow: float | None = None
    fixture_units: float | None = None
    electrical_kw: float | None = None

    if classification in AIR_CLASSIFICATIONS:
        terminals = [nodes_by_id[eid] for eid in elem_ids if nodes_by_id[eid].is_terminal]
        term_flows = [t.flow for t in terminals if t.flow is not None]
        if term_flows:
            air_flow = round(sum(term_flows), 3)
        else:
            leaf_flows = [
                nodes_by_id[eid].flow
                for eid in leaves
                if nodes_by_id[eid].is_run and nodes_by_id[eid].flow is not None
            ]
            if leaf_flows:
                air_flow = round(sum(leaf_flows), 3)
            else:
                all_duct_flows = [
                    nodes_by_id[eid].flow
                    for eid in elem_ids
                    if nodes_by_id[eid].is_run and nodes_by_id[eid].flow is not None
                ]
                if all_duct_flows:
                    air_flow = round(sum(all_duct_flows), 3)
                else:
                    if air_flows_cache is None:
                        air_flows_cache = _existing_air_flows(mep, building)
                    cached = [air_flows_cache[eid] for eid in leaves if eid in air_flows_cache]
                    if cached:
                        air_flow = round(sum(cached), 3)
                    else:
                        src_flows = [
                            nodes_by_id[eid].flow
                            for eid in elem_ids
                            if nodes_by_id[eid].is_source and nodes_by_id[eid].flow is not None
                        ]
                        if src_flows:
                            air_flow = round(sum(src_flows), 3)

    elif classification in WATER_CLASSIFICATIONS:
        fu_vals = [
            nodes_by_id[eid].fixture_units
            for eid in leaves
            if nodes_by_id[eid].fixture_units is not None
        ]
        if not fu_vals:
            fu_vals = [
                nodes_by_id[eid].fixture_units
                for eid in elem_ids
                if nodes_by_id[eid].fixture_units is not None
            ]
        if fu_vals:
            fixture_units = round(sum(fu_vals), 2)
        elif (
            mep.plumbing is not None
            and mep.plumbing.stories
            and classification
            in (
                "domesticColdWater",
                "domesticHotWater",
                "sanitary",
            )
        ):
            from saengine.plumbing.demand import drainage_units, supply_units

            served_stories: set[str] = set()
            for eid in elem_ids:
                node = nodes_by_id[eid]
                if node.serves:
                    served_stories.update(node.serves)
                elif node.stories_passed:
                    served_stories.update(node.stories_passed)
                elif node.story:
                    served_stories.add(node.story)
            fu = 0.0
            for ps in mep.plumbing.stories:
                if served_stories and ps.story not in served_stories:
                    continue
                if classification == "sanitary":
                    u, _, _ = drainage_units(
                        ps.fixtures, flush_valves=mep.plumbing.supply.flushValves
                    )
                else:
                    col = "hot" if classification == "domesticHotWater" else "cold"
                    u, _, _ = supply_units(
                        ps.fixtures, col, flush_valves=mep.plumbing.supply.flushValves
                    )
                fu += u
            if fu > 0:
                fixture_units = round(fu, 2)

        leaf_flows = [
            nodes_by_id[eid].flow
            for eid in leaves
            if (nodes_by_id[eid].is_run or nodes_by_id[eid].is_terminal)
            and nodes_by_id[eid].flow is not None
        ]
        if leaf_flows:
            water_flow = round(sum(leaf_flows), 3)
        elif fixture_units and fixture_units > 0 and mep.plumbing is not None:
            from saengine.plumbing.demand import hunter_flow

            water_flow = round(
                hunter_flow(fixture_units, mep.plumbing.supply.flushValves) / 60.0, 3
            )
        else:
            src_flows = [
                nodes_by_id[eid].flow
                for eid in elem_ids
                if nodes_by_id[eid].is_source and nodes_by_id[eid].flow is not None
            ]
            if src_flows:
                water_flow = round(sum(src_flows), 3)

    elif classification in ELECTRICAL_CLASSIFICATIONS:
        loads = [nodes_by_id[eid].load for eid in elem_ids if nodes_by_id[eid].load is not None]
        if not loads:
            loads = [
                p.load for eid in elem_ids for p in nodes_by_id[eid].ports if p.load is not None
            ]
        if loads:
            electrical_kw = round(sum(loads), 3)
        elif mep.electrical is not None and mep.electrical.stories:
            try:
                from saengine.electrical.demand import demand as electrical_demand
                from saengine.plumbing.building import Building

                rep = electrical_demand(mep.electrical, Building.of(building), mep)
                served: set[str] = set()
                for eid in elem_ids:
                    n = nodes_by_id[eid]
                    if n.serves:
                        served.update(n.serves)
                    elif n.stories_passed:
                        served.update(n.stories_passed)
                story_kw = {s["story"]: s["kw"] for s in rep.get("stories", [])}
                if served:
                    electrical_kw = round(sum(story_kw.get(s, 0.0) for s in served), 3)
            except Exception:  # noqa: BLE001, S110 - optional when building slabs absent
                pass

    return {
        "airFlowLps": air_flow,
        "waterFlowLps": water_flow,
        "fixtureUnits": fixture_units,
        "electricalLoadKw": electrical_kw,
    }


def analyze_systems(
    mep: MepModel, building: Any = None, tolerance: float = DEFAULT_TOLERANCE
) -> dict[str, Any]:
    """Derives connectors, snap-connects elements, builds logical systems and runs checks.

    Returns ``{"connectors", "connections", "systems", "issues", "unassigned", "summary"}``.
    """
    elements = _collect_elements(mep, building)
    nodes_by_id = {e.id: e for e in elements}
    connections, connected_keys = _snap_connections(elements, tolerance)

    # Port adjacency within each element (weighted by physical run length [m]).
    adj_ports: dict[str, list[tuple[str, float]]] = {}
    for elem in elements:
        if len(elem.ports) <= 1:
            continue
        ordered = sorted(elem.ports, key=lambda p: p.station)
        if elem.is_run:
            for a, b in itertools.pairwise(ordered):
                w = abs(b.station - a.station) / 1000.0
                if elem.is_riser:
                    w = abs(b.z - a.z) / 1000.0
                adj_ports.setdefault(a.key, []).append((b.key, w))
                adj_ports.setdefault(b.key, []).append((a.key, w))
        else:
            # Non-run equipment: only bridge ports of the same classification so AHU supply/return
            # remain separate logical networks.
            for a, b in itertools.combinations(ordered, 2):
                if a.classification == b.classification:
                    adj_ports.setdefault(a.key, []).append((b.key, 0.0))
                    adj_ports.setdefault(b.key, []).append((a.key, 0.0))

    # Cross-element connections in port graph (same-classification edges for traversal).
    elem_adj: dict[tuple[str, str], list[str]] = {}
    for conn in connections:
        if conn.a.classification == conn.b.classification:
            cls = conn.a.classification
            adj_ports.setdefault(conn.a.key, []).append((conn.b.key, 0.0))
            adj_ports.setdefault(conn.b.key, []).append((conn.a.key, 0.0))
            elem_adj.setdefault((conn.a.element_id, cls), []).append(conn.b.element_id)
            elem_adj.setdefault((conn.b.element_id, cls), []).append(conn.a.element_id)

    # Build systems by BFS from sources per classification.
    systems: list[dict[str, Any]] = []
    assigned_elements: set[str] = set()
    elem_to_systems: dict[str, list[str]] = {}
    visited_source_cls: set[tuple[str, str]] = set()
    air_cache: dict[str, float] | None = None

    sources = [e for e in elements if e.is_source]
    sys_num = 0
    for src in sources:
        src_classes = list(dict.fromkeys(p.classification for p in src.ports)) or [
            src.classification
        ]
        for cls in src_classes:
            if (src.id, cls) in visited_source_cls:
                continue
            # BFS across same-classification edges.
            queue = [src.id]
            visited_eids: list[str] = []
            seen_eids: set[str] = {src.id}
            parent_elem: dict[str, str | None] = {src.id: None}
            while queue:
                cur = queue.pop(0)
                visited_eids.append(cur)
                if nodes_by_id[cur].is_source:
                    visited_source_cls.add((cur, cls))
                for nxt in elem_adj.get((cur, cls), []):
                    if nxt not in seen_eids:
                        seen_eids.add(nxt)
                        parent_elem[nxt] = cur
                        queue.append(nxt)

            # Skip an isolated source that has no runs/terminals unless it is a standalone plant
            # (still a valid 1-element system or flagged via open connector).
            sys_num += 1
            sys_id = f"SYS{sys_num}"
            cls_label = SYSTEM_CLASSIFICATIONS.get(cls, cls)
            sys_sources = [eid for eid in visited_eids if nodes_by_id[eid].is_source]
            start_ports = [
                p for sid in sys_sources for p in nodes_by_id[sid].ports if p.classification == cls
            ]
            crit_len, crit_path = _critical_path(start_ports, nodes_by_id, adj_ports)
            if air_cache is None and cls in AIR_CLASSIFICATIONS:
                air_cache = _existing_air_flows(mep, building)
            totals = _system_totals(
                cls, visited_eids, parent_elem, nodes_by_id, mep, building, air_cache
            )
            assigned_elements.update(visited_eids)
            for eid in visited_eids:
                elem_to_systems.setdefault(eid, []).append(sys_id)
            systems.append(
                {
                    "id": sys_id,
                    "name": f"{src.id} ({cls_label})",
                    "classification": cls,
                    "classificationLabel": cls_label,
                    "domain": nodes_by_id[src.id].domain,
                    "sources": sys_sources,
                    "elements": visited_eids,
                    "elementCount": len(visited_eids),
                    **totals,
                    "criticalPathLength": crit_len,
                    "criticalPath": crit_path,
                    "warnings": 0,
                }
            )

    # Connectivity checks.
    issues: list[dict[str, Any]] = []

    def add_issue(
        kind: str,
        severity: str,
        message: str,
        elem_ids: list[str],
        point: list[float] | None,
        story: str | None = None,
        classification: str | None = None,
    ) -> None:
        sys_id = next((elem_to_systems[e][0] for e in elem_ids if e in elem_to_systems), None)
        issues.append(
            {
                "id": f"SI{len(issues) + 1}",
                "kind": kind,
                "severity": severity,
                "message": message,
                "elements": elem_ids,
                "story": story,
                "point": point,
                "system": sys_id,
                "classification": classification,
            }
        )

    # 1. Open (unconnected) connectors.
    for elem in elements:
        for port in elem.ports:
            if port.key not in connected_keys:
                add_issue(
                    "openConnector",
                    "warning",
                    f"{elem.id} ({port.port_id}): open {SYSTEM_CLASSIFICATIONS.get(port.classification, port.classification).lower()} connector",
                    [elem.id],
                    [round(port.x, 1), round(port.y, 1), round(port.z, 1)],
                    story=port.story or elem.story,
                    classification=port.classification,
                )

    # 2. Elements in no system.
    for elem in elements:
        if elem.id not in assigned_elements:
            add_issue(
                "unassignedElement",
                "warning",
                f"{elem.id} ({elem.kind}): not connected to any system source",
                [elem.id],
                elem.anchor,
                story=elem.story,
                classification=elem.classification,
            )

    # 3. Connection-level checks: mixed classifications, flow direction conflicts, size mismatches.
    for conn in connections:
        story = conn.a.story or conn.b.story
        if conn.a.classification != conn.b.classification:
            ca = SYSTEM_CLASSIFICATIONS.get(conn.a.classification, conn.a.classification)
            cb = SYSTEM_CLASSIFICATIONS.get(conn.b.classification, conn.b.classification)
            add_issue(
                "mixedClassification",
                "error",
                f"{conn.a.element_id} ({ca}) connected to {conn.b.element_id} ({cb}): mixed classification",
                [conn.a.element_id, conn.b.element_id],
                conn.point,
                story=story,
                classification=conn.a.classification,
            )
        if _direction_conflict(conn.a, conn.b):
            add_issue(
                "flowDirectionConflict",
                "error",
                f"{conn.a.element_id} ({conn.a.direction}) connected to {conn.b.element_id} ({conn.b.direction}): flow direction conflict",
                [conn.a.element_id, conn.b.element_id],
                conn.point,
                story=story,
                classification=conn.a.classification,
            )
        if not conn.is_tee:
            mismatch = _size_mismatch_detail(conn.a, conn.b)
            if mismatch:
                add_issue(
                    "sizeMismatch",
                    "warning",
                    f"{conn.a.element_id} to {conn.b.element_id}: size mismatch ({mismatch})",
                    [conn.a.element_id, conn.b.element_id],
                    conn.point,
                    story=story,
                    classification=conn.a.classification,
                )

    # Count warnings per system.
    warn_count: dict[str, int] = {}
    for issue in issues:
        if issue["system"]:
            warn_count[issue["system"]] = warn_count.get(issue["system"], 0) + 1
        for eid in issue["elements"]:
            for sid in elem_to_systems.get(eid, []):
                if sid != issue["system"]:
                    warn_count[sid] = warn_count.get(sid, 0) + 1
    for system in systems:
        system["warnings"] = warn_count.get(system["id"], 0)

    element_summaries = {
        e.id: {
            "id": e.id,
            "kind": e.kind,
            "discipline": e.discipline,
            "story": e.story,
            "domain": e.domain,
            "classification": e.classification,
            "isSource": e.is_source,
            "isTerminal": e.is_terminal,
            "flow": e.flow,
            "fixtureUnits": e.fixture_units,
            "load": e.load,
            "point": e.anchor,
            "connectors": [p.as_dict() for p in e.ports],
        }
        for e in elements
    }

    return {
        "systems": systems,
        "issues": issues,
        "elements": element_summaries,
        "connectors": [p.as_dict() for e in elements for p in e.ports],
        "connections": [
            {
                "from": c.a.key,
                "to": c.b.key,
                "elements": [c.a.element_id, c.b.element_id],
                "point": c.point,
                "tee": c.is_tee,
            }
            for c in connections
        ],
        "unassigned": [e.id for e in elements if e.id not in assigned_elements],
        "summary": {
            "systems": len(systems),
            "elements": len(elements),
            "connectors": sum(len(e.ports) for e in elements),
            "connections": len(connections),
            "issues": len(issues),
            "openConnectors": sum(1 for i in issues if i["kind"] == "openConnector"),
            "unassigned": sum(1 for i in issues if i["kind"] == "unassignedElement"),
            "mixedClassifications": sum(1 for i in issues if i["kind"] == "mixedClassification"),
            "flowConflicts": sum(1 for i in issues if i["kind"] == "flowDirectionConflict"),
            "sizeMismatches": sum(1 for i in issues if i["kind"] == "sizeMismatch"),
        },
    }


def issues_to_coordination(
    analysis: dict[str, Any],
    coordination: Coordination | None = None,
    ifc_ids: dict[str, str] | None = None,
) -> Coordination:
    """Converts MEP system connectivity issues into :class:`saengine.library.mep.Issue` entries."""
    from saengine.mep.coordination import merge_found

    base = coordination or Coordination()
    found = []
    for item in analysis.get("issues", []):
        guids = [ifc_ids.get(eid, eid) if ifc_ids else eid for eid in item.get("elements", [])]
        elems = ":".join(sorted(item.get("elements", [])))
        key = f"MEP-SYS:{item['kind']}:{elems}:{item['id']}"
        found.append(
            {
                "key": key,
                "test": "MEP-SYS",
                "title": item["message"],
                "description": item["message"],
                "elements": guids,
                "point": item.get("point"),
                "story": item.get("story"),
            }
        )
    merged, _ = merge_found(base, found, {"MEP-SYS"}, source="systems")
    return merged


def issues_to_bcf(
    analysis: dict[str, Any],
    ifc_ids: dict[str, str] | None = None,
    files: list[str] | None = None,
    author: str = "SAEngine",
) -> bytes:
    """Exports MEP system connectivity issues as a BCF 3.0 zip archive."""
    from saengine.mep.bcf import export_bcf

    coord = issues_to_coordination(analysis, Coordination(author=author), ifc_ids=ifc_ids)
    return export_bcf(coord, files=files)


def mep_systems_report(
    project_root: str | Path,
    mep_text: str | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    """Reads ``07 MEP/mep.json`` and ``06 BIM/bim.json`` and runs :func:`analyze_systems`."""
    from saengine.library.bim import BuildingModel

    root = Path(project_root)
    if mep_text is None:
        try:
            mep_text = (root / MEP_FILE).read_text(encoding="utf-8")
        except OSError:
            mep_text = None
    mep = parse(mep_text)
    building = None
    try:
        bim_raw = (root / "06 BIM" / "bim.json").read_text(encoding="utf-8")
        if bim_raw.strip():
            building = BuildingModel.model_validate_json(bim_raw)
    except (OSError, ValueError):
        building = None
    return analyze_systems(mep, building, tolerance=tolerance)

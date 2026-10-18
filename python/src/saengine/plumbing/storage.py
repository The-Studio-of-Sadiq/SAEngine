"""Water storage (BNBC 2020 Part 8 Sec 5.9): reservoir and overhead tank volumes and sizes.

- Volumes (Sec 5.9.1.2(c)): roof (overhead) tank = 1/2 the daily demand, underground reservoir
  = 1 x the daily demand, each plus a 1 hour reserve for fire fighting in a tall building. A
  building is tall here when a story with occupants is more than 33 m above the ground (the
  high-rise of Part 3 Sec 2.4.4). The reserve is 1 hour of the standpipe-and-hose flow of
  Part 4 Table 4.4.1 for the most severe hazard class of the building's occupancies (Part 8
  Sec 5.5.3.3 refers fire water storage to Part 4 Sec 4.2), times the number of standpipe
  risers: the table's values are for one riser serving 1000 m² (its note **), so SAEngine
  takes one riser per started 1000 m² of the largest floor; sprinkler flows are not included.
- Pipes: the drain of a tank by its capacity (Table 8.5.2), the overflow by the inflow (Table
  8.5.3): the pump's flow into the overhead tank, the source's into the reservoir.
- Dimensions (proposed, ``sized``): at least two compartments for alternate cleaning (Sec
  5.9.2.1), the partitions inside the inside length taking their share of the plan; SAEngine
  practice: square compartments side by side along X, water depth 1.5 m
  (overhead) or 2.0 m (underground) unless given, 300 mm freeboard, plan sizes rounded up to
  50 mm.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.plumbing import tables as T
from saengine.plumbing.building import Building

DEPTH = {"overhead": 1500.0, "underground": 2000.0, "rainwater": 2000.0}
FREEBOARD = 300.0
STEP = 50.0


def ceil_to(value: float, step: float = STEP) -> float:
    return math.ceil(value / step - 1e-9) * step


def pick(rows: list[tuple[float | None, int]], value: float) -> int:
    """The size of the first row whose upper bound holds ``value`` (None: no bound)."""
    for bound, size in rows:
        if bound is None or value <= bound:
            return size
    return rows[-1][1]


def tank_drain(volume: float) -> int:
    """Table 8.5.2: drain pipe [mm] of a tank of ``volume`` litres."""
    return pick(T.TANK_DRAIN, volume)


def tank_overflow(inflow: float) -> int:
    """Table 8.5.3: overflow pipe [mm] for an inflow of ``inflow`` l/min."""
    return pick(T.TANK_OVERFLOW, inflow)


def is_tall(plumbing: Any, building: Building) -> tuple[bool, str]:
    """Whether a story with occupants is above 33 m (Part 3 Sec 2.4.4)."""
    if not building.known:
        return False, "the building's height is unknown (no 06 BIM): no fire reserve"
    occupied = [s.story for s in plumbing.stories if s.story in building.stories]
    if not occupied:
        return False, "no occupied story in 06 BIM: no fire reserve"
    top = max(building.height(s) for s in occupied)
    tall = top > T.HIGH_RISE
    return tall, (
        f"highest occupied floor {top / 1000:.1f} m above ground "
        f"{'>' if tall else '<='} 33 m ({T.PAGES['3:2.4.4']}): "
        f"{'tall, fire reserve included' if tall else 'not tall, no fire reserve'}"
    )


def fire_reserve(plumbing: Any, building: Building) -> tuple[float, list[str]]:
    """Fire-fighting reserve in each tank [m³] and how it was found."""
    if plumbing.supply.fireReserve is not None:
        return float(plumbing.supply.fireReserve), ["fire reserve as entered in 07 MEP"]
    tall, note = is_tall(plumbing, building)
    if not tall:
        return 0.0, [note]
    hazards = [T.fire_hazard(T.OCCUPANCIES[s.occupancy].group) for s in plumbing.stories]
    known = [h for h in hazards if h]
    hazard = max(known, key=T.HAZARD_ORDER.index) if known else "lightII"
    notes = [note]
    if len(known) < len(hazards):
        notes.append("an occupancy Table 4.4.1 does not list is taken as light hazard-II")
    per_riser = T.FIRE_FLOWS[hazard][1]
    # Table 4.4.1 note **: the values are for one riser serving a floor area of 1000 m²;
    # SAEngine: one standpipe riser per started 1000 m² of the largest floor plate.
    area = max((building.floor_area(s.story) for s in plumbing.stories), default=0.0)
    risers = max(1, math.ceil(area / T.FIRE_RISER_AREA - 1e-9))
    flow = per_riser * risers
    volume = flow * 60 * T.FIRE_RESERVE_HOURS / 1000.0
    area_note = (
        f"largest floor {area:.0f} m², {risers} riser(s) of {T.FIRE_RISER_AREA:g} m² "
        f"(Table 4.4.1 note **)"
        if area > 0
        else "floor area unknown (no slabs): one riser (Table 4.4.1 note **: 1000 m² a riser)"
    )
    notes.append(
        f"fire reserve = {T.FIRE_RESERVE_HOURS:g} h x {risers} x {per_riser} l/min standpipe "
        f"flow ({hazard}, {T.PAGES['4.4.1']}; {area_note}) = {volume:g} m³ "
        f"({T.PAGES['5.9.1.2']})"
    )
    return volume, notes


def volumes(plumbing: Any, building: Building, daily: float) -> dict[str, Any]:
    """Required volumes [m³] of the overhead tank and the underground reservoir."""
    reserve, notes = fire_reserve(plumbing, building)
    daily_m3 = daily / 1000.0
    overhead = T.ROOF_TANK_FRACTION * daily_m3 + reserve
    underground = T.RESERVOIR_FRACTION * daily_m3 + reserve
    return {
        "daily": daily_m3,
        "fireReserve": reserve,
        "overhead": overhead,
        "underground": underground,
        "reference": T.PAGES["5.9.1.2"],
        "notes": [
            (
                f"overhead tank = 1/2 x {daily_m3:.2f} + {reserve:g} = {overhead:.2f} m³; "
                f"underground reservoir = 1 x {daily_m3:.2f} + {reserve:g} = {underground:.2f} m³"
            ),
            *notes,
        ],
    }


def dimensions(
    volume: float,
    kind: str,
    tank: Any = None,
    compartments: int = 2,
) -> dict[str, Any]:
    """Proposed inside dimensions [mm] of a rectangular tank holding ``volume`` m³ of water;
    what the tank entry gives (length, width, water depth, freeboard, compartments) is kept."""
    n = (tank.compartments if tank is not None and tank.compartments else None) or compartments
    freeboard = tank.freeboard if tank is not None and tank.freeboard else FREEBOARD
    length = tank.length if tank is not None else None
    width = tank.width if tank is not None else None
    depth = tank.waterDepth if tank is not None else None
    v = volume * 1e9  # mm³
    notes = []
    given_wall = tank.walls if tank is not None and tank.walls else None
    # The partitions stand inside the inside length and take their share of the plan, as the
    # tank design and the bill take them (saengine.plumbing.tanks.water_volume).
    wall = given_wall or default_wall((depth or DEPTH.get(kind, 1500.0)) + freeboard)
    parts = (n - 1) * wall
    if v <= 0:
        # Nothing to hold (no demand yet): keep what the tank gives, propose nothing.
        given = length and width and depth
        return {
            "length": length,
            "width": width,
            "waterDepth": depth,
            "freeboard": freeboard,
            "compartments": n,
            "partitionWall": wall,
            "volume": max(length - parts, 0.0) * width * depth / 1e9 if given else 0.0,
            "notes": ["no volume required (zero daily demand): not sized"],
        }
    if length and width:
        need = v / (max(length - parts, 1.0) * width)
        depth = ceil_to(need, 10.0) if depth is None or depth < need else depth
    else:
        depth = depth or DEPTH.get(kind, 1500.0)
        area = v / depth
        if width and not length:
            length = ceil_to(area / width + parts)
        elif length and not width:
            width = ceil_to(area / max(length - parts, 1.0))
        else:
            width = ceil_to(math.sqrt(area / n))
            length = ceil_to(area / width + parts)
    provided = max(length - parts, 0.0) * width * depth / 1e9
    if n < 2 and kind in ("overhead", "underground"):
        notes.append(f"at least two compartments for alternate cleaning ({T.PAGES['5.9.2.1']})")
    return {
        "length": length,
        "width": width,
        "waterDepth": depth,
        "freeboard": freeboard,
        "compartments": n,
        "partitionWall": wall,
        "volume": provided,
        "notes": notes,
    }


def default_wall(height: float) -> float:
    """The wall (and partition) thickness the tank design proposes when none is given [mm]:
    height / 12 in steps of 25 mm, at least 200 mm (``saengine.plumbing.tanks.tank_spec``)."""
    return max(150.0, math.ceil(height / 12 / 25.0 - 1e-9) * 25.0, 200.0)


def water_weight(tank: dict[str, Any]) -> float:
    """Weight of the water a tank of these dimensions holds [kN] (9.81 kN/m³), the partitions
    (``compartments`` - 1 of ``partitionWall`` or ``walls`` mm) taking their share of the plan."""
    if not (tank.get("length") and tank.get("width") and tank.get("waterDepth")):
        return 0.0
    n = int(tank.get("compartments") or 1)
    wall = tank.get("partitionWall") or tank.get("walls") or 0.0
    plan = max(tank["length"] - (n - 1) * wall, 0.0) * tank["width"]
    return plan * tank["waterDepth"] / 1e9 * 9.81

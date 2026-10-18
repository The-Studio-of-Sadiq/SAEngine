"""Sanitary drainage (BNBC 2020 Part 8 Sec 6.10): stacks, branches, vents, building drain.

- Load (Sec 6.10.1): drainage fixture units of Table 8.6.12 (Table 8.6.13 for the washing
  machine, by a 50 mm trap). Soil fixtures (water closets, urinals; Table 8.6.2's soil
  appliances) go to soil or soil-and-waste stacks, the others to waste or soil-and-waste
  stacks; a story's fixtures are shared equally by the stacks receiving them (SAEngine).
- Stack (Table 8.6.14): up to 3 storeys (branch intervals with fixtures) the "one stack of 3
  storeys" column; above, both the "total for stack" and the "total at one storey or branch
  interval" columns. Not smaller than the largest minimum outlet of Table 8.6.2 of a fixture
  it receives (100 mm with water closets; the soil branch at least 100 mm, Sec 6.9.3(a)).
- Branch on each story: the "any horizontal fixture branch" column, not below the outlets.
- Vent stack (Table 8.6.16): the row of the vented stack's diameter with the fixture units
  next above its load, the smallest vent whose maximum developed length is at least the vent
  stack's length (its height from 07 MEP, SAEngine). Branch vents (Table 8.6.17) are data.
- Building drain (Table 8.6.15): the total fixture units at the slope of 07 MEP (the column
  of the next flatter slope). With a septic tank, the soil and the waste (sullage) are drained
  apart (Sec 6.9.12.4, two-pipe system Sec 6.9.3(c)); with a public sewer, together.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.plumbing import tables as T
from saengine.plumbing.building import Building
from saengine.plumbing.demand import drainage_units
from saengine.plumbing.supply import crossings, served, sharing, story_order

STACKS = ("soil", "waste", "soilWaste")
RECEIVES = {"soil": ("soil",), "waste": ("waste",), "soilWaste": ("soil", "waste")}


def stack_capacity(diameter: int, storeys: int) -> tuple[float | None, float | None]:
    """Table 8.6.14: (total, per storey) fixture units a stack may carry."""
    for d, _branch, three, total, storey in T.STACKS:
        if d == diameter:
            if storeys <= 3:
                return three, None
            return total, storey
    return None, None


def stack_size(total: float, per_storey: float, storeys: int, outlet: float) -> int | None:
    for d, _branch, three, whole, storey in T.STACKS:
        if d < outlet:
            continue
        if storeys <= 3:
            if three is not None and total <= three:
                return d
        elif whole is not None and storey is not None and total <= whole and per_storey <= storey:
            return d
    return None


def branch_size(units: float, outlet: float) -> int | None:
    """Table 8.6.14: the horizontal fixture branch for ``units``."""
    for d, branch, *_ in T.STACKS:
        if d >= outlet and units <= branch:
            return d
    return None


def story_loads(stack: Any, plumbing: Any, building: Building, order: list[str]):
    """Fixture units and largest outlet each served story puts on a stack."""
    valves = plumbing.supply.flushValves
    entries = {s.story: s for s in plumbing.stories}
    soil_count = sharing(plumbing, building, order, ("soil", "soilWaste"))
    waste_count = sharing(plumbing, building, order, ("waste", "soilWaste"))
    loads: dict[str, tuple[float, float]] = {}
    for s in served(stack, building, order):
        entry = entries.get(s)
        if entry is None:
            continue
        units, outlet = 0.0, 0.0
        for kind in RECEIVES[stack.system]:
            u, o, _ = drainage_units(entry.fixtures, kind, valves)
            n = (soil_count if kind == "soil" else waste_count).get(s, 1) or 1
            if u:
                units += u / n
                outlet = max(outlet, o)
        loads[s] = (units, outlet)
    return loads


def soil_stack(stack: Any, plumbing: Any, building: Building) -> dict[str, Any]:
    """Size (or check) a soil, waste or soil-and-waste stack and its branches."""
    order = story_order(plumbing, building)
    loads = story_loads(stack, plumbing, building, order)
    total = sum(u for u, _ in loads.values())
    storeys = sum(1 for u, _ in loads.values() if u > 0)
    per_storey = max((u for u, _ in loads.values()), default=0.0)
    outlet = max((o for _, o in loads.values()), default=0.0)
    required = stack_size(total, per_storey, storeys, outlet)
    notes = []
    branches = [
        {"story": s, "units": u, "diameter": branch_size(u, o)} for s, (u, o) in loads.items()
    ]
    if stack.diameter is not None:
        whole, storey = stack_capacity(int(stack.diameter), storeys)
        ok = (
            whole is not None
            and total <= whole
            and (storey is None or per_storey <= storey)
            and stack.diameter >= outlet
        )
        if whole is None:
            notes.append(f"Ø{stack.diameter:g} is not a size of Table 8.6.14")
        elif not ok:
            notes.append(f"Ø{stack.diameter:g} is too small: needs Ø{required}")
        diameter = stack.diameter
    else:
        diameter = required
        ok = required is not None
        if not ok:
            notes.append("beyond Table 8.6.14: split the load into more stacks")
    if outlet >= 100:
        notes.append(
            f"receives water closets: at least 100 mm ({T.PAGES['8.6.2']}; {T.PAGES['6.9.3']})"
        )
    capacity = stack_capacity(int(diameter), storeys) if diameter else (None, None)
    return {
        "id": stack.id,
        "system": stack.system,
        "units": total,
        "storeys": storeys,
        "maxStoreyUnits": per_storey,
        "outlet": outlet,
        "diameter": diameter,
        "required": required,
        "capacity": capacity[0],
        "storeyCapacity": capacity[1],
        "ok": ok,
        "branches": branches,
        "notes": notes,
        "reference": f"{T.PAGES['8.6.12']}; {T.PAGES['8.6.14']}; {T.PAGES['8.6.2']}",
        "crossings": crossings(stack, building, order),
    }


def vent_size(stack_diameter: float, units: float, length: float) -> int | None:
    """Table 8.6.16: the smallest vent for a stack of this diameter and load, ``length`` m."""
    rows = [r for r in T.VENT_STACKS if r[0] == stack_diameter and units <= r[1]]
    if not rows:
        return None
    lengths = rows[0][2]
    for d in sorted(lengths):
        if lengths[d] >= length:
            return d
    return None


def vent_stack(vent: Any, stacks: list[dict[str, Any]], plumbing: Any, building: Building):
    """Size (or check) a vent stack for the soil or waste stack it vents."""
    candidates = [r for r in plumbing.risers if r.system in STACKS]
    notes = []
    if not candidates:
        return {
            "id": vent.id, "system": "vent", "units": 0, "diameter": vent.diameter,
            "required": None, "ok": vent.diameter is not None,
            "notes": ["no soil or waste stack to vent"], "reference": T.PAGES["8.6.16"],
        }  # fmt: skip
    same = [r for r in candidates if vent.shaft and r.shaft == vent.shaft]
    nearest = min(same or candidates, key=lambda r: math.hypot(r.x - vent.x, r.y - vent.y))
    vented = next(s for s in stacks if s["id"] == nearest.id)
    if building.known:
        length = (
            building.stories.get(vent.toStory, 0) - building.stories.get(vent.fromStory, 0)
        ) / 1000.0
    else:
        length = 0.0
    d_stack = vented["diameter"] or vented["required"] or 0
    required = vent_size(d_stack, vented["units"], length)
    notes.append(
        f"vents {nearest.id} (Ø{d_stack:g}, {vented['units']:g} units); developed length "
        f"{length:.1f} m"
    )
    if vent.diameter is not None:
        diameter = vent.diameter
        ok = required is not None and vent.diameter >= required
        if not ok:
            notes.append(f"Ø{vent.diameter:g} is too small: needs Ø{required}")
    else:
        diameter = required
        ok = required is not None
        if not ok:
            notes.append("beyond Table 8.6.16 for this stack")
    return {
        "id": vent.id,
        "system": "vent",
        "units": vented["units"],
        "flow": None,
        "diameter": diameter,
        "required": required,
        "ok": ok,
        "length": length,
        "vents": nearest.id,
        "notes": notes,
        "reference": T.PAGES["8.6.16"],
    }


def drain_size(units: float, slope: float) -> tuple[int | None, float | None]:
    """Table 8.6.15: building drain [mm] for ``units`` at ``slope``: (diameter, column)."""
    usable = [i for i, s in enumerate(T.DRAIN_SLOPES) if s <= slope + 1e-12]
    if not usable:
        return None, None
    i = usable[-1]
    for d, capacities in T.BUILDING_DRAINS:
        cap = capacities[i]
        if cap is not None and units <= cap:
            return d, T.DRAIN_SLOPES[i]
    return None, T.DRAIN_SLOPES[i]


def building_drains(plumbing: Any) -> list[dict[str, Any]]:
    """The building drain(s): soil and waste apart for a septic tank, else one."""
    valves = plumbing.supply.flushValves
    soil = sum(drainage_units(s.fixtures, "soil", valves)[0] for s in plumbing.stories)
    waste = sum(drainage_units(s.fixtures, "waste", valves)[0] for s in plumbing.stories)
    slope = plumbing.drainSlope
    parts = (
        [("soil", soil), ("waste", waste)]
        if plumbing.disposal == "septic"
        else [("combined", soil + waste)]
    )
    result = []
    for name, units in parts:
        if units <= 0:
            continue
        d, column = drain_size(units, slope)
        result.append({
            "name": name,
            "units": units,
            "slope": slope,
            "column": column,
            "diameter": d,
            "ok": d is not None,
            "note": (
                f"{units:g} units at 1/{1 / slope:.0f}"
                + (f" (Table 8.6.15 column 1/{1 / column:.0f})" if column else "")
                + ("" if d else ": slope flatter than 1/200 or beyond Table 8.6.15")
                + "; half full at 0.75 m/s self-cleansing, at most 2.5 m/s (Sec 6.10.2.1)"
            ),
            "reference": T.PAGES["8.6.15"],
        })  # fmt: skip
    return result

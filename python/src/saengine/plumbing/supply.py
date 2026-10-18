"""Water supply pipes (BNBC 2020 Part 8 Sec 5.10): risers, pump main, pump flow, heads.

- Flow in a riser: the water supply fixture units it carries (Appendix O Sec O.3, Table 8.O.1,
  Table 8.5.4 for the fixtures 8.O.1 lacks) turned into the probable simultaneous demand of
  Table 8.5.5 (flush tank or flush valve column). A story's fixtures are shared equally by the
  risers of the same system serving it (SAEngine). A cold water riser carries the cold units
  when the building has a hot water riser, the total units otherwise (Table 8.O.1).
- Down-feed (an overhead tank, Sec 5.8.2-5.8.4): through the slab of a story a riser carries
  the stories it serves below that story; up-feed (no overhead tank): those at and above it.
- Diameter (Sec 5.10.1(c)(ii)): the smallest of BNBC's sizes whose velocity is within the
  "probable maximum velocity" for its diameter (read as 13 mm 0.30, 50 mm 0.60, 75 mm 0.75,
  100 mm 0.90, 150 mm 1.15, 200 mm 1.30 m/s, interpolated) and whose Hazen-Williams friction
  loss is at most 1.6 m per 100 m (the Hazen-Williams formula is the one Sec 5.10.3 names; C
  by material, SAEngine), and not below the largest minimum supply pipe of Table 8.5.6 of the
  fixtures it serves. The nominal size is taken as the bore.
- Pump (Sec 5.9.1.2(c)(ii)): the delivery pump delivers the peak hourly demand (Eq 8.5.1),
  or, with the pumping hours given, the daily demand in those hours (two fillings of the
  half-day roof tank a day, Sec 5.9.1.2(c)(i)). The head is the hydraulics stream's.
- Heads (Table 8.5.6, Sec 5.10.4.2, 5.11.1): the minimum flow pressure at the fixtures (55 kPa;
  100 kPa with flush valves), at most 35 m of static head on a fitting: zones of intermediate
  tanks or pressure reducing valves above that.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

from saengine.plumbing import tables as T
from saengine.plumbing.building import Building
from saengine.plumbing.demand import hunter_flow, supply_units

SUPPLY = ("coldWater", "hotWater")


def velocity_limit(diameter: float) -> float:
    """Sec 5.10.1(c)(ii): the probable maximum velocity [m/s] for a pipe diameter [mm]."""
    rows = T.VELOCITY_LIMITS
    if diameter <= rows[0][0]:
        return rows[0][1]
    for (d0, v0), (d1, v1) in itertools.pairwise(rows):
        if diameter <= d1:
            return v0 + (diameter - d0) / (d1 - d0) * (v1 - v0)
    return rows[-1][1]


def head_loss(flow: float, diameter: float, c: float) -> float:
    """Hazen-Williams friction loss [m per 100 m] of ``flow`` l/min in a bore [mm]."""
    if flow <= 0:
        return 0.0
    q = flow / 60000.0
    d = diameter / 1000.0
    return 10.67 * q**1.852 / (c**1.852 * d**4.87) * 100.0


def velocity(flow: float, diameter: float) -> float:
    """[m/s] of ``flow`` l/min in a bore of ``diameter`` mm."""
    return flow / 60000.0 / (math.pi / 4 * (diameter / 1000.0) ** 2)


def size_pipe(flow: float, material: str | None = None, minimum: float = 0) -> dict[str, Any]:
    """The smallest BNBC size carrying ``flow`` l/min within the velocity and friction limits."""
    c = T.HAZEN_C.get(material or "uPVC", 150)
    for d in T.SUPPLY_DIAMETERS:
        if d < minimum:
            continue
        v = velocity(flow, d)
        hf = head_loss(flow, d, c)
        if v <= velocity_limit(d) + 1e-9 and hf <= T.MAX_HEAD_LOSS + 1e-9:
            return {"diameter": d, "velocity": v, "headLoss": hf, "vMax": velocity_limit(d)}
    d = T.SUPPLY_DIAMETERS[-1]
    return {
        "diameter": None,
        "velocity": velocity(flow, d),
        "headLoss": head_loss(flow, d, c),
        "vMax": velocity_limit(d),
    }


def capacity(diameter: float, material: str | None = None) -> float:
    """The largest flow [l/min] a bore carries within the velocity and friction limits."""
    c = T.HAZEN_C.get(material or "uPVC", 150)
    d = diameter / 1000.0
    by_velocity = velocity_limit(diameter) * math.pi / 4 * d * d * 60000.0
    by_friction = (T.MAX_HEAD_LOSS / 100.0 * c**1.852 * d**4.87 / 10.67) ** (1 / 1.852) * 60000.0
    return min(by_velocity, by_friction)


def check_pipe(flow: float, diameter: float, material: str | None = None) -> dict[str, Any]:
    c = T.HAZEN_C.get(material or "uPVC", 150)
    v = velocity(flow, diameter)
    hf = head_loss(flow, diameter, c)
    return {"velocity": v, "headLoss": hf, "vMax": velocity_limit(diameter)}


# ────────────────────────────────────── risers ──────────────────────────────────────


def passes(riser: Any, building: Building, order: list[str]) -> list[str]:
    """Stories a riser passes, lowest first (``order``: the stories when 06 BIM is missing)."""
    if building.known:
        return building.between(riser.fromStory, riser.toStory)
    if riser.fromStory in order and riser.toStory in order:
        i, j = order.index(riser.fromStory), order.index(riser.toStory)
        return order[i : j + 1]
    return []


def served(riser: Any, building: Building, order: list[str]) -> list[str]:
    stories = passes(riser, building, order)
    return [s for s in stories if s in riser.serves] if riser.serves else stories


def crossings(riser: Any, building: Building, order: list[str]) -> list[str]:
    """Stories whose floor slab a riser passes through: above its first story, up to its
    last (the convention of 07 MEP shafts)."""
    return passes(riser, building, order)[1:]


def sharing(plumbing: Any, building: Building, order: list[str], systems: tuple[str, ...]):
    """For each story, the number of risers of ``systems`` serving it."""
    count: dict[str, int] = {}
    for r in plumbing.risers:
        if r.system in systems:
            for s in served(r, building, order):
                count[s] = count.get(s, 0) + 1
    return count


def down_feed(plumbing: Any) -> bool:
    """Water comes down from an overhead tank (else up from the main or a pump): the
    supply's ``feed``, down unless set to "up". The report proposes an overhead tank exactly
    when this is true, so the risers and the proposals agree."""
    return plumbing.supply.feed != "up"


def story_order(plumbing: Any, building: Building) -> list[str]:
    """Stories lowest first: 06 BIM's, else the order of 07 MEP's plumbing stories."""
    if building.known:
        return building.ordered()
    return [s.story for s in plumbing.stories]


def supply_riser(riser: Any, plumbing: Any, building: Building) -> dict[str, Any]:
    """Size (or check) a cold or hot water riser."""
    order = story_order(plumbing, building)
    valves = plumbing.supply.flushValves
    hot_exists = any(r.system == "hotWater" for r in plumbing.risers)
    column = "hot" if riser.system == "hotWater" else ("cold" if hot_exists else "total")
    count = sharing(plumbing, building, order, (riser.system,))
    entries = {s.story: s for s in plumbing.stories}
    stories = served(riser, building, order)
    per_story: dict[str, float] = {}
    minimum = 0
    notes = []
    for s in stories:
        entry = entries.get(s)
        if entry is None:
            continue
        units, least, _ = supply_units(entry.fixtures, column, valves)
        n = max(count.get(s, 1), 1)
        per_story[s] = units / n
        if units:
            minimum = max(minimum, least)
    if any(count.get(s, 1) > 1 for s in per_story):
        notes.append("a story's fixtures are shared equally by the risers serving it")
    down = down_feed(plumbing)
    level = {s: i for i, s in enumerate(order)}
    segments = []
    for s in crossings(riser, building, order):
        if down:
            carried = sum(u for t, u in per_story.items() if level.get(t, -1) < level[s])
        else:
            carried = sum(u for t, u in per_story.items() if level.get(t, -1) >= level[s])
        flow = hunter_flow(carried, valves)
        size = size_pipe(flow, riser.material, minimum)
        segments.append({"story": s, "units": carried, "flow": flow, **size})
    total = sum(per_story.values())
    flow = hunter_flow(total, valves)
    sized = size_pipe(flow, riser.material, minimum)
    if riser.diameter is not None:
        got = check_pipe(flow, riser.diameter, riser.material)
        ok = (
            got["velocity"] <= got["vMax"] + 1e-9
            and got["headLoss"] <= T.MAX_HEAD_LOSS + 1e-9
            and riser.diameter >= minimum
        )
        diameter = riser.diameter
        if not ok:
            notes.append(
                f"Ø{riser.diameter:g}: {got['velocity']:.2f} m/s (limit {got['vMax']:.2f}), "
                f"{got['headLoss']:.2f} m/100 m (limit {T.MAX_HEAD_LOSS}); needs "
                f"Ø{sized['diameter'] or '> 200'}"
            )
    else:
        diameter = sized["diameter"]
        ok = diameter is not None
        got = sized
        if not ok:
            notes.append("more than a 200 mm riser: split it into more risers")
    notes.append(
        f"{'down' if down else 'up'}-feed; {column} units (Appendix O, Table 8.O.1); Table "
        f"8.5.5 {'flush valve' if valves else 'flush tank'} column"
    )
    return {
        "id": riser.id,
        "system": riser.system,
        "units": total,
        "flow": flow,
        "diameter": diameter,
        "required": sized["diameter"],
        "velocity": got["velocity"],
        "headLoss": got["headLoss"],
        "minimum": minimum,
        "ok": ok,
        "segments": segments,
        "notes": notes,
        "reference": f"{T.PAGES['O']}; {T.PAGES['8.5.5']}; {T.PAGES['5.10.1']}; {T.PAGES['8.5.6']}",
    }


def pump(plumbing: Any, daily: float) -> dict[str, Any]:
    """Delivery pump flow [l/min] (Sec 5.9.1.2(c)(ii)); the head is left to the hydraulics."""
    from saengine.plumbing.demand import peak_hourly

    peak = peak_hourly(daily) / 60.0
    hours = plumbing.supply.pumpHours
    if hours:
        flow = daily / hours / 60.0
        note = (
            f"daily demand {daily / 1000:.2f} m³ in {hours:g} pumping hours (two fillings of "
            f"the roof tank, {T.PAGES['5.9.1.2']}) = {flow:.1f} l/min"
        )
    else:
        flow = peak
        note = f"peak hourly demand (Eq 8.5.1, {T.PAGES['5.9.1.2']}) = {flow:.1f} l/min"
    return {"flow": flow, "peakHourly": peak, "hours": hours, "note": note}


def pump_main(riser: Any, flow: float) -> dict[str, Any]:
    """Size (or check) the pump main (rising main) for the pump's flow."""
    sized = size_pipe(flow, riser.material)
    notes = [f"pump flow {flow:.1f} l/min"]
    if riser.diameter is not None:
        got = check_pipe(flow, riser.diameter, riser.material)
        ok = got["velocity"] <= got["vMax"] + 1e-9 and got["headLoss"] <= T.MAX_HEAD_LOSS + 1e-9
        diameter = riser.diameter
        if not ok:
            notes.append(f"Ø{riser.diameter:g} is too small: needs Ø{sized['diameter']}")
    else:
        got = sized
        diameter = sized["diameter"]
        ok = diameter is not None
    return {
        "id": riser.id,
        "system": riser.system,
        "units": None,
        "flow": flow,
        "diameter": diameter,
        "required": sized["diameter"],
        "velocity": got["velocity"],
        "headLoss": got["headLoss"],
        "ok": ok,
        "segments": [],
        "notes": notes,
        "reference": f"{T.PAGES['5.9.1.2']}; {T.PAGES['5.10.1']}",
    }


def heads(plumbing: Any, building: Building) -> dict[str, Any]:
    """Minimum residual head at the fixtures and the static head limit (for the hydraulics)."""
    valves = plumbing.supply.flushValves
    kpa = T.FLOW_PRESSURE_VALVE if valves else T.FLOW_PRESSURE_TANK
    minimum = plumbing.supply.minResidualHead or kpa / 9.807
    notes = [
        f"minimum residual head {minimum:.1f} m"
        + ("" if plumbing.supply.minResidualHead else f" ({kpa:g} kPa, {T.PAGES['8.5.6']})"),
        (
            f"static head on any fitting at most {T.MAX_STATIC_HEAD:g} m "
            f"({T.PAGES['5.10.4.2']}; 350 kPa, {T.PAGES['5.11.1']})"
        ),
    ]
    fixtures = [s.story for s in plumbing.stories if s.story in building.stories]
    result: dict[str, Any] = {
        "minResidualHead": minimum,
        "maxStaticHead": T.MAX_STATIC_HEAD,
        "mainsHead": plumbing.supply.mainsHead,
        "notes": notes,
    }
    if fixtures:
        top = max(building.height(s) for s in fixtures) / 1000.0
        low = min(building.height(s) for s in fixtures) / 1000.0
        result["highestFixtureLevel"] = top
        result["lowestFixtureLevel"] = low
        # The overhead tank's bottom must be at least the residual head above the highest
        # fixture (Sec 5.9.2.2) plus the friction, which the hydraulics stream adds.
        result["tankBottomAbove"] = top + minimum
        span = top + minimum - low
        zones = max(1, math.ceil(span / T.MAX_STATIC_HEAD - 1e-9))
        result["zones"] = zones
        if zones > 1:
            notes.append(
                f"{span:.1f} m of static head from the tank to the lowest fixture: {zones} "
                f"zones (intermediate tanks every 5 - 6 storeys or pressure reducing valves, "
                f"{T.PAGES['5.11.1']})"
            )
    main = plumbing.supply.mainsHead
    if plumbing.supply.source == "mains" and main is not None and main < minimum:
        notes.append(
            f"the main's {main:g} m is below the residual head: feed an underground "
            "reservoir (Sec 5.8.3)"
        )
    return result

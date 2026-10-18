"""The substation, generator and electrical shaft requirements of BNBC 2020 Part 8 Chapter 1
checked against where 07 MEP places the equipment.

- Substation (Sec 1.3.18.2, 1.3.18.7, p796-800): an 11 kV/0.4 kV one not in a basement (one of
  higher voltage "may also be considered" there with a safe building design, Sec 1.3.18.3,
  p798); preferably on the ground
  floor; on a floor above it only with the Fire Service's no objection, the building
  consultant's certificate of ventilation, access and the safe load bearing capacity of the
  floor (the structural engineer's), and the owner's undertaking.
- Transformer room (Sec 1.3.18.3, p797-798): height 3.0 m to 3.6 m by the transformer's size;
  0.75 m / 1.0 m / 1.25 m from the transformer to the walls (walls on two sides, three sides,
  enclosed), 1.5 m between transformers at 11 kV (2.5 m above); a soak pit for more than
  2000 litres of oil; the areas of Table 8.1.23 (with windows and independent doors). Dry type
  transformers for hospitals and multistoried shopping centres (Sec 1.3.18.4).
- Generator room (Sec 1.3.19.2-1.3.19.3, p801-802): on the ground floor or the first basement
  (a basement preferably avoided; a second or deeper basement fails); 1.0 m from the set to the walls of an enclosed room, 1.25 m
  between sets; shock absorbing mountings; the areas of Table 8.1.24.
- Electrical shaft (Sec 1.3.13.1, p790-791): above six storeys or 20 m at least one 200 x
  400 mm shaft for every 1500 m² of floor area, not adjacent to the sanitary shafts.

A room outline (07 MEP ``electrical.rooms``) is checked when given; without one the clearances
between the units are.
"""

from __future__ import annotations

import math
from typing import Any

from shapely.geometry import Point, Polygon, box

from saengine.electrical import tables as T
from saengine.electrical.supply import generator_area, substation_area
from saengine.plumbing.building import Building

#: A story more than this below the ground level is a basement [mm] (SAEngine).
BASEMENT_DEPTH = 600.0


def _check(name: str, demand: float, cap: float | None, unit: str, ok: bool, note: str):
    util = demand / cap if cap else (0.0 if demand == 0 else math.inf)
    return {"name": name, "demand": demand, "capacity": cap, "unit": unit,
            "utilisation": util, "ok": bool(ok), "note": note}  # fmt: skip


def storeys_and_height(building: Building, order: list[str]) -> tuple[int, float]:
    """(storeys above the ground, roof height above the ground in m): the stories at or above
    the ground below the top level (the roof)."""
    if not building.known:
        return max(len(order) - 1, 0), 0.0
    levels = [building.stories[s] for s in building.ordered()]
    above = [z for z in levels if z >= building.ground - BASEMENT_DEPTH]
    storeys = max(len(above) - 1, 0)
    return storeys, (max(levels) - building.ground) / 1000.0


def ground_story(building: Building) -> str | None:
    """The lowest story at or above the ground (within 600 mm below it)."""
    for s in building.ordered():
        if building.stories[s] >= building.ground - BASEMENT_DEPTH:
            return s
    return None


def placement(story: str, building: Building) -> str:
    """'basement', 'ground', 'upper' or 'unknown'."""
    if story not in building.stories:
        return "unknown"
    if building.stories[story] < building.ground - BASEMENT_DEPTH:
        return "basement"
    return "ground" if story == ground_story(building) else "upper"


def basement_level(story: str, building: Building) -> int:
    """1 for the first basement (the one right below the ground), 2 for the second, ...; 0 for
    a story that is not a basement."""
    if placement(story, building) != "basement":
        return 0
    below = [
        s
        for s in building.ordered()
        if building.stories[s] < building.ground - BASEMENT_DEPTH
        and building.stories[s] >= building.stories[story]
    ]
    return len(below)


def footprint(item: dict[str, Any]) -> Polygon | None:
    if not item.get("length") or not item.get("width"):
        return None
    hx, hy = item["length"] / 2, item["width"] / 2
    return box(item["x"] - hx, item["y"] - hy, item["x"] + hx, item["y"] + hy)


def clear_height(story: str, building: Building, slab_thickness: dict[str, float]) -> float | None:
    """Floor to the soffit of the floor above [mm] (None without the floor above)."""
    order = building.ordered()
    if story not in order or order.index(story) + 1 >= len(order):
        return None
    above = order[order.index(story) + 1]
    slabs = building.slabs_at(above)
    thickness = max((slab_thickness.get(s, 150.0) for s, _ in slabs), default=150.0)
    return building.stories[above] - building.stories[story] - thickness


def covered(item: dict[str, Any], building: Building) -> bool:
    """Whether a slab of the story above stands over the item's centre (it is indoors)."""
    order = building.ordered()
    story = item.get("story")
    if story not in order or order.index(story) + 1 >= len(order):
        return False
    point = Point(item["x"], item["y"])
    for above in order[order.index(story) + 1 :]:
        slabs = building.slabs_at(above)
        if slabs:
            return any(poly.buffer(1.0).covers(point) for _, poly in slabs)
    return False


def room_of(item: dict[str, Any], rooms: list[Any]) -> Any:
    point = Point(item["x"], item["y"])
    for room in rooms:
        if room.story == item["story"] and Polygon(room.outline).buffer(0).covers(point):
            return room
    return None


def room_checks(
    electrical: Any,
    equipment: list[dict[str, Any]],
    building: Building,
    slab_thickness: dict[str, float],
    uses: set[str],
) -> dict[str, Any]:
    """The checks of the transformers' and generators' rooms. ``equipment``: the electrical
    equipment as dicts (entered, or proposed where none is entered)."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []
    supply = electrical.supply
    rooms = electrical.rooms
    hv = "33kV" if supply.voltage == "33kV" else "11kV"
    transformers = [e for e in equipment if e["kind"] == "transformer"]
    generators = [e for e in equipment if e["kind"] == "generator"]
    for tx in transformers:
        where = placement(tx["story"], building)
        if where == "basement" and hv == "11kV":
            checks.append(_check(f"{tx['id']} location", 1, 0, "", False,
                                 f"an 11 kV/0.4 kV substation shall not be placed in a basement "
                                 f"({T.cite('1.3.18.7', '(g)')})"))  # fmt: skip
        elif where == "basement":
            checks.append(_check(f"{tx['id']} location", 0, 0, "", True,
                                 f"a {supply.voltage} substation in a basement: may be "
                                 "considered with a proper and safe building design "
                                 f"({T.PAGES['1.3.18.3']}); the ban of "
                                 f"{T.cite('1.3.18.7', '(g)')} is for 11 kV/0.4 kV"))  # fmt: skip
            notes.append(
                f"{tx['id']} ({supply.voltage}) is in a basement: design the room for the "
                "transformer's weight, the soak pit, flooding and storm water, ventilation and "
                "fire separation"
            )
        elif where == "upper":
            checks.append(_check(f"{tx['id']} location", 0, 0, "", True,
                                 f"above the ground floor (to be avoided, "
                                 f"{T.cite('1.3.18.7', '(h)')}): needs the Fire Service's no objection and the building "
                                 f"consultant's certificate of the floor's load bearing capacity "
                                 f"({T.PAGES['1.3.18.2']})"))  # fmt: skip
            notes.append(
                f"{tx['id']} stands above the ground floor: certify the floor for the "
                "transformer's weight (07 MEP equipment) and ventilation, access and escape"
            )
        oil = tx.get("oil") or 0.0
        if supply.transformerType == "oil" and oil > T.SOAK_PIT_OIL:
            checks.append(_check(f"{tx['id']} soak pit", oil, T.SOAK_PIT_OIL, "l", True,
                                 f"more than {T.SOAK_PIT_OIL:g} l of oil: provide a soak pit "
                                 f"under it ({T.cite('1.3.18.3', '(c)')}) - a pit in the floor "
                                 "structure"))  # fmt: skip
        height = None
        room = room_of(tx, rooms)
        if room is not None and room.height:
            height = room.height
        elif covered(tx, building):
            height = clear_height(tx["story"], building, slab_thickness)
        else:
            notes.append(
                f"{tx['id']} is not under a slab of the story above (outside the building or "
                "in the open): taken as an outdoor substation, its room height is not checked; "
                "enter a room in 07 MEP electrical if it stands in one"
            )
        if height is not None:
            need = T.SUBSTATION_HEIGHT[0]
            checks.append(_check(f"{tx['id']} room height", need, height, "mm", height >= need,
                                 f"3.0 m to 3.6 m by the transformer's size "
                                 f"({T.cite('1.3.18.3', '(a)')})"))  # fmt: skip
    if supply.transformerType == "oil" and uses & {"hospital", "departmentStore"} and transformers:
        checks.append(_check("Transformer type", 1, 0, "", False,
                             "dry type transformers should be used for hospitals and "
                             f"multistoried shopping centres ({T.PAGES['1.3.18.4']})"))  # fmt: skip
    for gen in generators:
        where = placement(gen["story"], building)
        level = basement_level(gen["story"], building)
        if where == "upper" or level > 1:
            at = "above the ground floor" if where == "upper" else f"in basement {level}"
            checks.append(_check(f"{gen['id']} location", 1, 0, "", False,
                                 f"{at}: the generator shall be placed either on the ground "
                                 f"floor or in the first basement ({T.PAGES['1.3.19.3']})"))  # fmt: skip
        elif where == "basement":
            checks.append(_check(f"{gen['id']} location", 0, 0, "", True,
                                 "in a basement (preferably avoided): the owner's special "
                                 f"safety measures ({T.PAGES['1.3.19.3']})"))  # fmt: skip
    checks.extend(_spacing(transformers, T.TRANSFORMER_SPACING[hv], "transformers",
                           T.PAGES["1.3.18.3"]))  # fmt: skip
    checks.extend(_spacing(generators, T.GENERATOR_SPACING, "generators", T.PAGES["1.3.19.2"]))
    for room in rooms:
        checks.extend(_room(room, equipment, supply))
    if not rooms and (transformers or generators):
        notes.append(
            "no substation or generator room outline in 07 MEP: the clearances to the walls "
            f"({T.TRANSFORMER_CLEARANCE['enclosed'] / 1000:g} m round a transformer in an "
            f"enclosed room, {T.GENERATOR_CLEARANCE / 1000:g} m round a generator) are not checked"
        )
    return {"checks": checks, "notes": notes}


def _spacing(items: list[dict[str, Any]], need: float, what: str, source: str):
    checks = []
    shapes = [(i, footprint(i)) for i in items]
    for a in range(len(shapes)):
        for b in range(a + 1, len(shapes)):
            (ia, pa), (ib, pb) = shapes[a], shapes[b]
            if pa is None or pb is None or ia["story"] != ib["story"]:
                continue
            gap = pa.distance(pb)
            checks.append(_check(f"{ia['id']}-{ib['id']} spacing", need, gap, "mm",
                                 gap >= need - 1e-6, f"between {what} ({source})"))  # fmt: skip
    return checks


def _room(room: Any, equipment: list[dict[str, Any]], supply: Any) -> list[dict[str, Any]]:
    polygon = Polygon(room.outline).buffer(0)
    area = polygon.area / 1e6
    inside = [e for e in equipment if e["story"] == room.story and
              polygon.covers(Point(e["x"], e["y"]))]  # fmt: skip
    checks = []
    tx = [e for e in inside if e["kind"] == "transformer"]
    gens = [e for e in inside if e["kind"] == "generator"]
    if room.kind in ("substation", "transformer") and tx:
        rating = max(float(e.get("rating") or 0.0) for e in tx)
        row = substation_area(len(tx), rating)
        if row is not None:
            need = row[1] if room.kind == "substation" else row[0]
            checks.append(_check(f"{room.id} area", need, area, "m²", area >= need - 1e-9,
                                 f"{row[2]} kVA, {T.PAGES['8.1.23']}"))  # fmt: skip
        else:
            checks.append(_check(f"{room.id} area", 0, area, "m²", True,
                                 f"{len(tx)} x {rating:g} kVA is not in Table 8.1.23: lay out "
                                 "the room to the clearances"))  # fmt: skip
    if room.kind == "generator" and gens:
        kw = sum(float(e.get("rating") or 0.0) * T.GENERATOR_PF for e in gens)
        row = generator_area(kw / len(gens))
        if row is not None:
            need = row[0] * len(gens)
            checks.append(_check(f"{room.id} area", need, area, "m²", area >= need - 1e-9,
                                 f"{row[1]} a set, {T.PAGES['8.1.24']}"))  # fmt: skip
    clearance = {"transformer": T.TRANSFORMER_CLEARANCE["enclosed"],
                 "generator": T.GENERATOR_CLEARANCE}  # fmt: skip
    for item in [*tx, *gens]:
        shape = footprint(item)
        if shape is None:
            continue
        need = clearance[item["kind"]]
        if not polygon.covers(shape):
            checks.append(_check(f"{item['id']} in {room.id}", 1, 0, "", False,
                                 "the unit does not fit inside the room's outline"))  # fmt: skip
            continue
        gap = polygon.exterior.distance(shape)
        source = T.PAGES["1.3.18.3"] if item["kind"] == "transformer" else T.PAGES["1.3.19.2"]
        checks.append(_check(f"{item['id']} clearance to the walls", need, gap, "mm",
                             gap >= need - 1e-6,
                             f"enclosed room ({source})"))  # fmt: skip
    return checks


def shaft_checks(
    mep: Any, building: Building, storeys: int, height_m: float, max_area: float
) -> list[dict[str, Any]]:
    """Sec 1.3.13.1: the number and size of the electrical shafts; not beside sanitary ones."""
    electrical = mep.electrical
    if storeys <= T.SHAFT_STOREYS and height_m <= T.SHAFT_HEIGHT:
        return []
    ids = {r.shaft for r in electrical.risers if r.shaft}
    for shaft in mep.shafts:
        if "elec" in (shaft.service or "").lower() or any(
            Polygon(shaft.outline).buffer(0).covers(Point(r.x, r.y)) for r in electrical.risers
        ):
            ids.add(shaft.id)
    shafts = [s for s in mep.shafts if s.id in ids]
    need = max(1, math.ceil(max_area / T.SHAFT_AREA - 1e-9)) if max_area > 0 else 1
    checks = [_check("Electrical shafts", need, len(shafts), "", len(shafts) >= need,
                     f"one {T.SHAFT_SIZE[0]:g} x {T.SHAFT_SIZE[1]:g} mm shaft for every "
                     f"{T.SHAFT_AREA:g} m² of floor ({max_area:.0f} m²) above six storeys or "
                     f"20 m ({T.PAGES['1.3.13.1']})")]  # fmt: skip
    plumbing_shafts = set()
    if mep.plumbing is not None:
        for r in mep.plumbing.risers:
            if r.shaft:
                plumbing_shafts.add(r.shaft)
    for shaft in shafts:
        poly = Polygon(shaft.outline).buffer(0)
        minx, miny, maxx, maxy = poly.bounds
        small, large = sorted((maxx - minx, maxy - miny))
        ok = small >= T.SHAFT_SIZE[0] - 1e-6 and large >= T.SHAFT_SIZE[1] - 1e-6
        checks.append(_check(f"Shaft {shaft.id} size", T.SHAFT_SIZE[0], small, "mm", ok,
                             f"{small:g} x {large:g} mm, at least {T.SHAFT_SIZE[0]:g} x "
                             f"{T.SHAFT_SIZE[1]:g} ({T.PAGES['1.3.13.1']})"))  # fmt: skip
        for other in mep.shafts:
            if other.id in plumbing_shafts and other.id != shaft.id:
                gap = poly.distance(Polygon(other.outline).buffer(0))
                if gap < 1.0:
                    checks.append(_check(f"Shaft {shaft.id} beside {other.id}", 1, 0, "", False,
                                         "an electrical shaft must not be placed adjacent to a "
                                         f"sanitary shaft ({T.PAGES['1.3.13.1']})"))  # fmt: skip
    return checks

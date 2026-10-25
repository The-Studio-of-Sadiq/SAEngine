"""The fire protection of 7 MEP in the bill of quantities (:mod:`saengine.boq.quantities`).

:func:`measure_fire` adds to a bill being measured: the fire tanks (reinforced concrete, as the
plumbing tanks: concrete, formwork, the ground tanks' excavation and the bars of their last
design), the fire pipes by size, the sprinkler heads, the valves, hose cabinets and Siamese
connections, the pump sets by duty, the portable extinguishers and the alarm devices, from the
fire report (:func:`saengine.fire.report.fire_results`).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

#: The measurement of the fire protection of 7 MEP, added when there is any.
FIRE_CONVENTIONS = [
    (
        "Fire protection of 7 MEP (BNBC 2020 Part 4): fire tanks measured as the plumbing tanks "
        "(concrete, formwork, ground tanks' excavation, bars from their last design); fire "
        "pipes by nominal size: risers vertically from the story they start at to their top "
        "outlet, mains along their path, each sprinklered floor's branch lines and cross main "
        "estimated from its heads (a head's spacing of branch pipe each, the cross main the "
        "side of the floor's square); sprinkler heads, landing valves with hose cabinets (one a "
        "floor a standpipe), floor control valve sets, riser gate and check valves, Siamese "
        "connections, pump sets, portable extinguishers, call points and detectors counted "
        "(number). Fittings, hangers and supports are not measured (their loads are in the "
        "report)."
    ),
]


def measure_fire(measure: Any, designs: dict[str, Any] | None = None) -> bool:
    """Adds the fire items to ``measure`` (a :class:`saengine.boq.quantities._Measure`);
    whether there was anything to measure."""
    mep = measure.mep
    fire = getattr(mep, "fire", None)
    if fire is None or not (fire.stories or fire.risers or fire.tanks or fire.pumps):
        return False
    from saengine.boq.quantities import MM2, MM3, TANK_BARS_PENDING, WORKING_SPACE
    from saengine.fire.report import fire_results
    from saengine.library.mep import FIRE_PUMP_DUTIES
    from saengine.plumbing.project import tank_stamp
    from saengine.plumbing.tanks import TankContext, tank_spec, volumes

    latest = {
        (entry.get("id"), entry.get("tank")): entry.get("result") or {}
        for entry in (designs or {}).values()
        if isinstance(entry, dict)
    }
    context = TankContext(materials=measure.materials)
    for tank in fire.tanks:
        if tank.construction != "rc" or tank.kind not in ("overhead", "underground"):
            measure.notes.append(f"{tank.id}: fire tank ({tank.construction}) is not measured")
            continue
        data = tank.model_dump(mode="json", exclude_none=True)
        try:
            spec = tank_spec(data, context)
        except ValueError as error:
            measure.notes.append(f"{tank.id}: not measured: {error}")
            continue
        v = volumes(spec)
        material = measure.materials[spec.concrete]
        measure.concrete(tank.id, material, "tank", v["concrete"] / MM3, tank.story)
        measure.formwork(
            tank.id, "tank", v["formwork"] / MM2, tank.story, "inside and outside faces"
        )
        if spec.ground:
            depth = spec.height + spec.base + (spec.roof or 0.0) - spec.top_level
            w = spec.width + 2 * spec.wall + 2 * spec.toe + 2 * WORKING_SPACE / 1000.0
            length = spec.length + 2 * spec.wall + 2 * spec.toe + 2 * WORKING_SPACE / 1000.0
            measure.bill.add("earthwork", (60, "fireTank"), "Excavation for fire tanks", "m3",
                             tank.id, max(depth, 0.0) * w * length, kind="excavation")  # fmt: skip
        design = latest.get((tank.id, tank_stamp(data)))
        bars = (design.get("quantities") or {}).get("byDiameter") if design else None
        if not bars:
            measure.notes.append(f"{tank.id}: {TANK_BARS_PENDING} (open the Fire results of 7 "
                                 "MEP, or Run All, to design the fire tanks)")  # fmt: skip
            continue
        for dia_text, mass in bars.items():
            dia = float(dia_text)
            measure.bill.add(
                "reinforcement", (spec.rebar, dia), f"Reinforcement {spec.rebar}, {dia:g} mm bars",
                "kg", tank.id, float(mass), story=tank.story, detail="fire tank design",
                material=spec.rebar, diameter=dia,
            )  # fmt: skip

    try:
        objects = SimpleNamespace(objects=list(measure.types.values()))
        report = fire_results(mep, measure.building, objects, measure.ground_level)
    except Exception as error:  # noqa: BLE001 - the rest of the bill is still measured
        measure.notes.append(f"fire: not sized ({error}); fire pipes not measured")
        return True
    q = report.get("quantities") or {}
    material = {"steel": "black steel", "GI": "galvanised steel", "copper": "copper"}[
        fire.supply.material
    ]
    for row in q.get("pipes", []):
        size = float(row["size"])
        measure.bill.add("mep", (80, "firePipe", size), f"Fire pipes, {material}, DN{size:g}",
                         "m", "fire", float(row["length"]), kind="pipe")  # fmt: skip
    counts = [
        (81, "heads", "Sprinkler heads, K80 standard spray", q.get("heads", 0)),
        (82, "landing", "Landing valves with hose reel cabinets (30 m hose)",
         q.get("hoseCabinets", 0)),
        (83, "floorValve", "Sprinkler floor control valve sets", q.get("floorValves", 0)),
        (84, "riserValve", "Fire riser gate and check valves", q.get("riserValves", 0)),
        (85, "siamese", "Siamese (fire brigade inlet) connections", q.get("siamese", 0)),
        (87, "extinguisher", "Portable fire extinguishers", q.get("extinguishers", 0)),
        (88, "callPoint", "Manual fire alarm call points", q.get("callPoints", 0)),
        (89, "detector", "Automatic fire detectors", q.get("detectors", 0)),
    ]  # fmt: skip
    for order, key, label, n in counts:
        measure.bill.add("mep", (order, key), label, "nr", "fire", float(n), kind="fire")
    for pump in fire.pumps:
        label = FIRE_PUMP_DUTIES[pump.duty]
        duty = f", {pump.flow:g} l/min x {pump.head:g} m" if pump.flow and pump.head else ""
        measure.bill.add("mep", (86, "firePump", pump.duty, pump.flow or 0.0, pump.head or 0.0),
                         f"Fire pump sets: {label.lower()}{duty}", "nr", pump.id, 1.0,
                         story=pump.story, kind="equipment")  # fmt: skip
    return True

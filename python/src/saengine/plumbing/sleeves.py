"""Sleeves for the risers and stacks through the slabs, and the shaft areas.

BNBC 2020 Part 8 gives no sleeve size for a pipe passing through a floor. SAEngine practice:
a sleeve's inside diameter is the pipe's outside diameter plus 50 mm (25 mm all round for
movement and fire stopping), rounded up to a standard size; the outside diameter of the
nominal size by material (plastics ISO metric, metal ISO 65). A riser needs a sleeve through
the slab of every story it crosses (the stories above its first, up to its last, as 07 MEP's
shafts count them) where it is not in a shaft or an opening of 06 BIM. The proposed sleeves
are 07 MEP openings (host: the slab of 06 BIM under the riser), so the existing opening checks
(:mod:`saengine.mep.openings`) run on them once they are added.

Shaft area (SAEngine practice): each pipe in a shaft takes a clear square of its outside
diameter plus 100 mm; their sum is checked against the shaft's plan area.
"""

from __future__ import annotations

import math
from typing import Any

from shapely.geometry import Point, Polygon

from saengine.plumbing import tables as T
from saengine.plumbing.building import Building
from saengine.plumbing.supply import passes, story_order

METAL = ("GI", "CI")


def outside_diameter(nominal: float, material: str | None) -> float:
    """Outside diameter [mm] of a nominal size (the next listed size up when not listed)."""
    table = T.OUTSIDE_DIAMETER["metal" if material in METAL else "plastic"]
    for size in sorted(table):
        if nominal <= size + 1e-9:
            return float(table[size])
    return float(nominal) * 1.08


def sleeve_diameter(nominal: float, material: str | None) -> float:
    need = outside_diameter(nominal, material) + T.SLEEVE_CLEARANCE
    for size in T.SLEEVE_SIZES:
        if size >= need - 1e-9:
            return float(size)
    return float(math.ceil(need / 50.0) * 50.0)


def _in_shaft(mep: Any, riser: Any, story: str, building: Building) -> str | None:
    """The shaft of 07 MEP the riser passes in on this story, if any."""
    p = Point(riser.x, riser.y)
    for shaft in mep.shafts:
        if not Polygon(shaft.outline).buffer(0).covers(p):
            continue
        if building.known and shaft.fromStory in building.stories:
            lo = building.stories[shaft.fromStory]
            hi = building.stories.get(shaft.toStory, lo)
            if not lo < building.stories.get(story, lo) <= hi:
                continue
        return shaft.id
    return None


def proposed_openings(
    mep: Any, sizes: dict[str, dict[str, Any]], building: Building
) -> dict[str, Any]:
    """Proposed sleeves (07 MEP openings) for every riser, from its sized diameters.

    ``sizes``: riser id -> {"diameter": mm, "segments": [{"story", "diameter"}]} (the
    segments of a water riser may be smaller than its base)."""
    plumbing = mep.plumbing
    order = story_order(plumbing, building)
    existing = {o.id for o in mep.openings}
    openings = []
    notes = []
    for riser in plumbing.risers:
        size = sizes.get(riser.id) or {}
        nominal = riser.diameter or size.get("diameter")
        if not nominal:
            notes.append(f"{riser.id}: no diameter, no sleeve")
            continue
        by_story = {s["story"]: s.get("diameter") for s in size.get("segments", [])}
        for story in passes(riser, building, order)[1:]:
            d = riser.diameter or by_story.get(story) or nominal
            shaft = _in_shaft(mep, riser, story, building)
            if shaft is not None:
                continue
            slab = building.slab_at(story, riser.x, riser.y)
            if slab is None:
                notes.append(f"{riser.id}: no slab of {story} under ({riser.x:g}, {riser.y:g})")
                continue
            if building.in_hole(slab, riser.x, riser.y):
                continue
            oid = f"PS-{riser.id}-{story}"
            if oid in existing:
                continue
            sleeve = sleeve_diameter(d, riser.material)
            openings.append({
                "id": oid, "host": slab, "kind": "sleeve", "shape": "circle",
                "diameter": sleeve, "position": {"x": riser.x, "y": riser.y},
                "service": f"DN{d:g} {T_SYSTEM.get(riser.system, riser.system)} {riser.id}",
            })  # fmt: skip
    notes.append(
        f"sleeve = pipe outside diameter + {T.SLEEVE_CLEARANCE:g} mm, next standard size "
        "(SAEngine practice; BNBC 2020 Part 8 gives no sleeve rule)"
    )
    return {"openings": openings, "notes": notes}


T_SYSTEM = {
    "coldWater": "cold water riser",
    "hotWater": "hot water riser",
    "soil": "soil stack",
    "waste": "waste stack",
    "soilWaste": "soil and waste stack",
    "vent": "vent stack",
    "rainwater": "rainwater leader",
    "pumpMain": "pump main",
}


def shaft_checks(mep: Any, sizes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Clear area the pipes of each shaft need against the shaft's plan area."""
    plumbing = mep.plumbing
    checks = []
    for shaft in mep.shafts:
        polygon = Polygon(shaft.outline).buffer(0)
        inside = [
            r for r in plumbing.risers if r.shaft == shaft.id or polygon.covers(Point(r.x, r.y))
        ]
        if not inside:
            continue
        need = 0.0
        notes = []
        for r in inside:
            d = r.diameter or (sizes.get(r.id) or {}).get("diameter")
            if not d:
                continue
            od = outside_diameter(d, r.material)
            need += (od + T.SHAFT_CLEARANCE) ** 2
            if r.shaft == shaft.id and not polygon.covers(Point(r.x, r.y)):
                notes.append(f"{r.id} is outside the shaft's outline")
        area = polygon.area
        checks.append({
            "name": f"Shaft {shaft.id} area", "demand": need / 1e6, "capacity": area / 1e6,
            "unit": "m²", "utilisation": need / area if area else math.inf,
            "ok": need <= area and not notes,
            "note": "; ".join([(f"{len(inside)} pipes, each (OD + {T.SHAFT_CLEARANCE:g} mm)² "
                               "(SAEngine practice)"), *notes]),
        })  # fmt: skip
    return checks

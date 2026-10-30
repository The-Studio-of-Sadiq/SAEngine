"""The branch runs from the risers and stacks to the wet rooms of the architecture, for the
structural coordination (where the horizontal pipes cross the beams).

For each wet room (:mod:`saengine.mep.rooms`) on a story the rooms' plan graph
(:class:`saengine.mep.routing.RoomGraph`) gives the run from each riser or stack that serves the
story (``fromStory`` up to ``toStory``, and in ``serves`` when given) to the room, through the
corridors, shafts and wet rooms first. The riser whose run costs least is the room's:

- supply: a cold water riser (a hot water riser where there is none), its run in the ceiling,
  so the beams it crosses are those of the floor above;
- drainage: a soil stack for a toilet, a waste stack for a kitchen, laundry or floor drain (a
  soil and waste stack for either, any stack where there is no such one), its run under the
  room's own floor, so the beams it crosses are those of the room's floor.

A run that crosses a beam passes below it or through a sleeve in its web (an opening in 07 MEP,
checked there). This is SAEngine's coordination layout, not a pipe design: BNBC 2020 Part 8
sizes the risers and stacks (Appendix O, Sec 6.10), not where their branches go.
"""

from __future__ import annotations

from typing import Any

from saengine.mep.routing import RoomGraph, RoomPlace, path_beam_crossings, path_length

#: Below this sine of the crossing angle a run goes along a beam, not across it (as the
#: cable trays, :data:`saengine.electrical.risers.MIN_SINE`).
MIN_SINE = 0.17

SUPPLY = ("coldWater", "hotWater")
SOIL = ("soil", "soilWaste", "waste")
WASTE = ("waste", "soilWaste", "soil")


def _serves(riser: Any, story: str, building: Any) -> bool:
    if riser.serves:
        return story in riser.serves
    if building.known:
        return story in building.between(riser.fromStory, riser.toStory)
    return story in (riser.fromStory, riser.toStory)


def _beams(bim: Any, building: Any, story: str, above: bool) -> list[Any]:
    from saengine.electrical.risers import Frame

    order = building.ordered()
    if story not in order:
        return []
    i = order.index(story) + (1 if above else 0)
    if i >= len(order):
        return []
    return Frame.of(bim).beams_at(building.stories[order[i]])


def _places(story: Any, risers: list[Any], shafts: list[Any]) -> list[RoomPlace]:
    from shapely.geometry import Point, Polygon

    outlines = [Polygon(s.outline) for s in shafts]
    places = []
    for room in story.rooms:
        holds = any(room.face.covers(Point(r.x, r.y)) for r in risers) or any(
            room.face.intersects(o) for o in outlines
        )
        preferred = room.kind is not None or room.circulation or holds
        places.append(RoomPlace(room.id, room.face, preferred))
    return places


def branch_runs(
    plumbing: Any, inputs: Any, building: Any, bim: Any = None, shafts: list[Any] | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """The runs to every wet room: ``[{room, label, story, system ("supply" | "drainage"),
    riser, path ([[x, y]] mm), length (m), beams ([ids] crossed)}]``, and notes."""
    runs: list[dict[str, Any]] = []
    notes: list[str] = []
    if plumbing is None or inputs is None:
        return runs, notes
    for name, story in inputs.stories.items():
        if not story.wet:
            continue
        risers = [r for r in plumbing.risers if _serves(r, name, building)]
        shafts_here = [
            s
            for s in shafts or []
            if not building.known or name in building.between(s.fromStory, s.toStory)
        ]
        graph = RoomGraph(_places(story, risers, shafts_here))
        beams = {
            "supply": _beams(bim, building, name, above=True) if bim is not None else [],
            "drainage": _beams(bim, building, name, above=False) if bim is not None else [],
        }
        for room in story.wet:
            toilet = room.kind in ("toilet", "halfBath", "publicToilet")
            for system, wanted in (("supply", SUPPLY), ("drainage", SOIL if toilet else WASTE)):
                best = None
                for preference in wanted:
                    found = []
                    for riser in risers:
                        if riser.system != preference:
                            continue
                        cost = graph.cost((riser.x, riser.y), room.id)
                        if cost is not None:
                            found.append((cost, riser))
                    if found:
                        best = min(found, key=lambda f: f[0])[1]
                        break
                if best is None:
                    kind = "supply riser" if system == "supply" else "stack"
                    notes.append(f"{room.label or room.id} ({name}): no {kind} serves the story")
                    continue
                path = graph.route((best.x, best.y), room.id) or []
                crossings = path_beam_crossings(path, beams[system], MIN_SINE)
                runs.append(
                    {
                        "room": room.id,
                        "label": room.label,
                        "story": name,
                        "system": system,
                        "riser": best.id,
                        "path": [[round(x, 1), round(y, 1)] for x, y in path],
                        "length": round(path_length(path) / 1000.0, 2),
                        "beams": list(dict.fromkeys(c.beam.id for c in crossings)),
                    }
                )
    return runs, notes

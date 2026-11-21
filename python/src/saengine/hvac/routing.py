"""HVAC duct auto-routing from an AHU/FCU to each room's diffuser through corridors and
ceiling voids (:class:`saengine.mep.routing.RoomGraph`).

Reuses :class:`~saengine.mep.routing.RoomGraph` (with corridor spine nodes and structural
beam-crossing penalties) and sizes the resulting duct tree with
:func:`saengine.hvac.air.size_duct_network` so the routed segments work directly with
:func:`saengine.hvac.air.duct_sizes`, :func:`saengine.hvac.openings.duct_openings`, and
:mod:`saengine.drawings.sheets.mep`.
"""

from __future__ import annotations

import inspect
import itertools
import math
from typing import Any

from saengine.hvac.air import FRICTION_RATE, INSULATION, size_duct_network
from saengine.mep.routing import SAME_POINT, RoomGraph, RoomPlace, path_beam_crossings
from saengine.plumbing.building import Building

#: Minimum sine of crossing angle below which a duct runs along a beam, not across it.
MIN_SINE = 0.17
#: Default penalty [mm equivalent] added per beam crossing when routing ducts.
DEFAULT_BEAM_PENALTY = 5000.0
#: Clear hanger/void margin [mm] subtracted from ceiling void depth when checking duct height.
VOID_MARGIN = 50.0


def _ceiling_void_depth(
    arch: Any,
    story: str,
    bim: Any = None,
    objects: Any = None,
) -> tuple[float | None, str | None]:
    """Query ``saengine.library.architecture.ceiling_void`` if it exists; skip if absent."""
    from saengine.library import architecture as arch_lib

    fn = getattr(arch_lib, "ceiling_void", None)
    if fn is None or arch is None:
        return None, "ceiling_void() not available in architecture.py: ceiling void check skipped"
    sig = inspect.signature(fn)
    positional = [
        p
        for p in sig.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if len(positional) <= 2:
        depth = fn(arch, story)
    else:
        if bim is None:
            return None, f"{story}: BIM model not provided: ceiling void check skipped"
        targets: list[Any] = [
            r for r in getattr(arch, "rooms", []) if getattr(r, "story", None) == story
        ]
        if not targets:
            targets = [
                c.id for c in getattr(arch, "ceilings", []) if getattr(c, "story", None) == story
            ]
        depths = [
            float(d) for t in targets if (d := fn(arch, bim, objects, t, story=story)) is not None
        ]
        depth = min(depths) if depths else None
    if depth is None:
        return None, f"{story}: ceiling_void() returned no depth: ceiling void check skipped"
    return float(depth), f"{story}: ceiling void depth {float(depth):g} mm checked"


def _story_beams(bim: Any, story: str) -> list[Any]:
    """Beams of the floor above ``story`` (where horizontal ceiling ducts run)."""
    if bim is None:
        return []
    from saengine.electrical.risers import Frame

    building = Building.of(bim)
    order = building.ordered()
    if story not in order:
        return []
    idx = order.index(story) + 1
    if idx >= len(order):
        return []
    return Frame.of(bim).beams_at(building.stories[order[idx]])


def _places_from_story(story_rooms: Any) -> list[RoomPlace]:
    """Build :class:`RoomPlace` entries from a :class:`~saengine.mep.rooms.StoryRooms`."""
    places: list[RoomPlace] = []
    for room in story_rooms.rooms:
        preferred = bool(getattr(room, "circulation", False) or getattr(room, "kind", None))
        places.append(RoomPlace(room.id, room.face, preferred))
    return places


def _pt_key(pt: tuple[float, float]) -> tuple[float, float]:
    return (round(float(pt[0]), 1), round(float(pt[1]), 1))


def _bend_fittings(path: list[list[float]]) -> list[str]:
    """Infer elbow fittings from angle changes along a polyline path."""
    fittings: list[str] = []
    for a, b, c in zip(path, path[1:], path[2:], strict=False):
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 <= SAME_POINT or l2 <= SAME_POINT:
            continue
        dot = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)))
        angle = math.degrees(math.acos(dot))
        if angle >= 60.0:
            fittings.append("elbow_90_radius")
        elif angle >= 20.0:
            fittings.append("elbow_45")
    return fittings


def _room_airflows(
    room_loads: dict[str, float] | list[dict[str, Any]], story: str
) -> dict[str, float]:
    """Map ``{room_id: airflow_m3s}`` from a dict or a list of load/zone dicts."""
    if isinstance(room_loads, dict):
        return {str(k): float(v) for k, v in room_loads.items() if float(v) > 0}
    out: dict[str, float] = {}
    for row in room_loads:
        if row.get("story") not in (None, story):
            continue
        rid = row.get("room")
        flow = row.get("airflow") or 0.0
        if rid and flow > 0:
            out[str(rid)] = float(flow)
    return out


def auto_route_ducts(
    story: str,
    start_point: tuple[float, float],
    room_loads: dict[str, float] | list[dict[str, Any]],
    rooms: Any,
    *,
    bim: Any = None,
    arch: Any = None,
    objects: Any = None,
    system: str = "supply",
    shape: str = "rect",
    method: str = "equalFriction",
    rate: float = FRICTION_RATE,
    beam_penalty: float = DEFAULT_BEAM_PENALTY,
    material: str | None = None,
    prefix: str = "D",
) -> dict[str, Any]:
    """Auto-route ducts from ``start_point`` (AHU/FCU, mm) to every room diffuser in
    ``room_loads`` on ``story`` through corridors/ceiling voids using :class:`RoomGraph`.

    ``rooms`` may be a :class:`~saengine.mep.rooms.RoomInputs`, a
    :class:`~saengine.mep.rooms.StoryRooms`, a list of :class:`~saengine.mep.routing.RoomPlace`,
    or an existing :class:`~saengine.mep.routing.RoomGraph`.

    Returns ``{"ducts", "pressure", "totalLength", "beamsCrossed", "ceilingVoid", "notes"}``
    where each item in ``ducts`` is compatible with 07 MEP ``Duct``, ``air.duct_sizes``,
    ``openings.duct_openings``, and ``drawings.sheets.mep``.
    """
    notes: list[str] = []
    flows = _room_airflows(room_loads, story)
    if not flows:
        return {
            "ducts": [],
            "pressure": None,
            "totalLength": 0.0,
            "beamsCrossed": [],
            "ceilingVoid": None,
            "notes": [f"{story}: no positive room airflows to route"],
        }

    beams = _story_beams(bim, story)
    if isinstance(rooms, RoomGraph):
        graph = rooms
    else:
        if isinstance(rooms, list):
            places = rooms
        elif hasattr(rooms, "story"):
            st = rooms.story(story)
            places = _places_from_story(st) if st is not None else []
        elif hasattr(rooms, "rooms"):
            places = _places_from_story(rooms)
        else:
            places = []
        if not places:
            return {
                "ducts": [],
                "pressure": None,
                "totalLength": 0.0,
                "beamsCrossed": [],
                "ceilingVoid": None,
                "notes": [f"{story}: no rooms available for duct routing"],
            }
        graph = RoomGraph(places, beams=beams, beam_penalty=beam_penalty, spine=True)

    void_depth, void_note = _ceiling_void_depth(arch, story, bim=bim, objects=objects)
    if void_note:
        notes.append(void_note)
    max_height: float | None = None
    if void_depth is not None:
        ins = INSULATION.get(system, 0.0)
        max_height = max(void_depth - 2 * ins - VOID_MARGIN, 100.0)

    raw_paths = graph.route_tree(tuple(start_point[:2]), list(flows))
    missing = [rid for rid in flows if rid not in raw_paths]
    for rid in missing:
        notes.append(f"{story} / {rid}: unreachable from AHU/FCU in RoomGraph")
    if not raw_paths:
        return {
            "ducts": [],
            "pressure": None,
            "totalLength": 0.0,
            "beamsCrossed": [],
            "ceilingVoid": void_depth,
            "notes": notes,
        }

    # Build directed tree of unique edges (u_key -> v_key), accumulating downstream airflows.
    edge_flow: dict[tuple[tuple[float, float], tuple[float, float]], float] = {}
    edge_rooms: dict[tuple[tuple[float, float], tuple[float, float]], list[str]] = {}
    children_of: dict[tuple[float, float], list[tuple[float, float]]] = {}
    parent_of: dict[tuple[float, float], tuple[float, float]] = {}
    root_key = _pt_key(tuple(start_point[:2]))
    leaf_room: dict[tuple[float, float], str] = {}

    for rid, pts in raw_paths.items():
        q = flows[rid]
        if len(pts) < 2:
            continue
        leaf_room[_pt_key(pts[-1])] = rid
        for a, b in itertools.pairwise(pts):
            ka, kb = _pt_key(a), _pt_key(b)
            if ka == kb:
                continue
            edge = (ka, kb)
            edge_flow[edge] = edge_flow.get(edge, 0.0) + q
            edge_rooms.setdefault(edge, []).append(rid)
            if kb not in parent_of:
                parent_of[kb] = ka
                children_of.setdefault(ka, []).append(kb)

    # Collapse degree-2 intermediate nodes (no tee/branch split) into multi-point duct segments.
    segments: list[dict[str, Any]] = []
    seg_counter = 0

    def walk(start_node: tuple[float, float], parent_id: str | None) -> None:
        nonlocal seg_counter
        kids = children_of.get(start_node, [])
        for nxt in kids:
            pts_chain = [[start_node[0], start_node[1]], [nxt[0], nxt[1]]]
            first_edge = (start_node, nxt)
            cur = nxt
            while len(children_of.get(cur, [])) == 1 and cur not in leaf_room:
                only = children_of[cur][0]
                if abs(edge_flow[(cur, only)] - edge_flow[first_edge]) > 1e-9:
                    break
                pts_chain.append([only[0], only[1]])
                cur = only
            seg_counter += 1
            sid = f"{prefix}-{story}-{seg_counter}"
            is_leaf = not children_of.get(cur)
            role = "main" if parent_id is None else ("runout" if is_leaf else "branch")
            fittings = _bend_fittings(pts_chain)
            if parent_id is not None:
                fittings.append(
                    "tee_branch" if len(children_of.get(start_node, [])) > 1 else "tee_main"
                )
            if is_leaf:
                fittings.extend(["damper_open", "diffuser"])
            seg: dict[str, Any] = {
                "id": sid,
                "parent": parent_id,
                "system": system,
                "shape": shape,
                "story": story,
                "path": pts_chain,
                "flow": edge_flow[first_edge],
                "role": role,
                "fittings": fittings,
                "servesRooms": edge_rooms[first_edge],
            }
            if material is not None:
                seg["material"] = material
            if cur in leaf_room:
                seg["room"] = leaf_room[cur]
            segments.append(seg)
            walk(cur, sid)

    walk(root_key, None)

    sized = size_duct_network(
        segments,
        system=system,
        shape=shape,
        method=method,
        rate=rate,
        max_height=max_height,
        material=material,
    )
    duct_keys = (
        "id",
        "system",
        "shape",
        "width",
        "height",
        "diameter",
        "story",
        "path",
        "bottom",
        "riser",
        "shaft",
        "flow",
        "material",
        "fittings",
        "parent",
        "room",
        "role",
        "terminalDrop",
    )
    ducts = [{k: d[k] for k in duct_keys if k in d} for d in sized["ducts"]]
    total_length = 0.0
    crossed_beams: list[str] = []
    for d in ducts:
        path = d["path"]
        total_length += sum(math.dist(a, b) for a, b in itertools.pairwise(path)) / 1000.0
        if beams:
            for c in path_beam_crossings(path, beams, MIN_SINE):
                if c.beam.id not in crossed_beams:
                    crossed_beams.append(c.beam.id)
        if void_depth is not None and d.get("height"):
            out_h = float(d["height"]) + 2 * INSULATION.get(system, 0.0)
            if out_h > void_depth + 1e-6:
                notes.append(
                    f"{d['id']}: outside height {out_h:g} mm exceeds ceiling void {void_depth:g} mm"
                )

    return {
        "ducts": ducts,
        "pressure": sized["pressure"],
        "totalLength": round(total_length, 3),
        "beamsCrossed": crossed_beams,
        "ceilingVoid": void_depth,
        "notes": notes,
    }

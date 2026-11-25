"""Sprinklers of a floor: heads, the design area and the pipe schedule (the code pack's fire
protection: BNBC 2020 Part 4 in the default pack).

Each sprinkler covers at most the ceiling area of Table 4.4.7 (p333) at no more than its spacing;
the heads of a floor are the more of its area over that coverage and a square grid at the
spacing over the floor's plan extent (a layout estimate: the drawings place the heads). The pipe
sizes of the schedule method are those of Tables 4.4.5 (steel) and 4.4.6 (copper) by the heads a
pipe supplies; one riser serves at most 4850 m² of floor (light and ordinary) or 2325 m²
(extra). The design area and density for the hydraulic calculation are NFPA 13's (from memory,
to be checked): the default pack (BNBC 2020 Part 4) asks for "the hydraulically calculated sprinkler demand"
(Sec 4.2.3.5) but gives no curve.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.fire import tables as T


def schedule_size(heads: int, hazard: str, material: str = "steel") -> int | None:
    """The smallest nominal size [mm] of Table 4.4.5 (steel, GI) or 4.4.6 (copper) that may
    supply ``heads`` sprinklers; None beyond the table."""
    column = {"light": 1, "ordinary": 2, "extra": 3}[T.family(hazard)]
    rows = T.COPPER_SCHEDULE if material == "copper" else T.STEEL_SCHEDULE
    for row in rows:
        limit = row[column]
        if limit is None or heads <= limit:
            return int(row[0])
    return None


def coverage(hazard: str, ceiling: str) -> tuple[float, float]:
    """Table 4.4.7: protected area [m²] and maximum spacing [m] of one sprinkler."""
    return T.COVERAGE.get(ceiling, T.COVERAGE["beams"])[T.family(hazard)]


def floor_sprinklers(
    area: float,
    hazard: str,
    ceiling: str = "beams",
    extent: tuple[float, float] | None = None,
    material: str = "steel",
) -> dict[str, Any]:
    """The sprinklers of a floor of ``area`` m² whose plan extent is ``extent`` (x, y) [m]:
    heads, their spacing, the design area and its heads, the per-head and total design flows,
    the risers the floor needs and the schedule size of the floor main."""
    cover, spacing = coverage(hazard, ceiling)
    side = min(spacing, math.sqrt(cover))
    by_area = math.ceil(area / cover - 1e-9) if area > 0 else 0
    by_grid = 0
    if extent and extent[0] > 0 and extent[1] > 0:
        grid = math.ceil(extent[0] / side - 1e-9) * math.ceil(extent[1] / side - 1e-9)
        # the grid over the extent, in the share of it the floor covers
        by_grid = math.ceil(grid * min(1.0, area / (extent[0] * extent[1])) - 1e-9)
    heads = max(by_area, by_grid)
    per_head = area / heads if heads else cover
    density, design = T.DENSITY_AREA[hazard]
    design_area = min(design, area)
    design_heads = max(1, math.ceil(design_area / per_head - 1e-9)) if heads else 0
    k_min = T.K_FACTOR * math.sqrt(T.MIN_HEAD_PRESSURE / 100.0)
    q_head = max(density * per_head, k_min)
    risers = max(1, math.ceil(area / T.RISER_FLOOR_AREA[T.family(hazard)] - 1e-9))
    main = schedule_size(heads, hazard, material) if heads else None
    length = T.DESIGN_AREA_LENGTH * math.sqrt(design_area) if design_area > 0 else 0.0
    per_branch = max(1, math.ceil(length / side - 1e-9)) if heads else 0
    branches = math.ceil(design_heads / per_branch - 1e-9) if per_branch else 0
    return {
        "hazard": hazard,
        "area": round(area, 1),
        "coverage": cover,
        "maxSpacing": spacing,
        "spacing": round(side, 2),
        "heads": heads,
        "perHead": round(per_head, 2),
        "density": density,
        "designArea": round(design_area, 1),
        "designHeads": design_heads,
        "headFlow": round(q_head, 1),
        "demand": round(density * design_area, 1),
        "risersNeeded": risers,
        "mainSize": main,
        "branches": branches,
        "headsPerBranch": per_branch,
        "notes": [
            (
                f"{heads} heads: {area:.0f} m² at most {cover:g} m² a head, {spacing:g} m apart "
                f"({T.cite('4.4.7')}, {T.HAZARD_LABELS[hazard]}); a layout estimate"
            ),
            (
                f"design area {design_area:.0f} m² at {density:g} mm/min (NFPA 13 density/area, "
                f"{T.MEMORY}): {design_heads} heads of at least {q_head:.0f} l/min (K{T.K_FACTOR:g} "
                f"at {T.MIN_HEAD_PRESSURE / 100:g} bar least, {T.MEMORY})"
            ),
        ],
    }


def hose_allowance(hazard: str) -> tuple[float, int]:
    """NFPA 13 inside and outside hose allowance [l/min] and the duration [min] (from memory)."""
    return T.HOSE_ALLOWANCE[T.family(hazard)]


def hand_demand(hazard: str, design_area: float | None = None) -> dict[str, Any]:
    """The sprinkler demand by hand: density x design area + hose allowance (NFPA 13, from
    memory)."""
    density, area = T.DENSITY_AREA[hazard]
    area = area if design_area is None else design_area
    hose, minutes = hose_allowance(hazard)
    sprinklers = density * area
    return {
        "density": density,
        "area": area,
        "sprinklers": sprinklers,
        "hose": hose,
        "total": sprinklers + hose,
        "duration": minutes,
        "note": (
            f"{density:g} mm/min x {area:g} m² = {sprinklers:.0f} l/min + hose {hose:g} l/min = "
            f"{sprinklers + hose:.0f} l/min for {minutes} min (NFPA 13, {T.MEMORY})"
        ),
    }


def place_room_sprinklers(
    outline: Any,
    hazard: str,
    ceiling: str = "beams",
    *,
    max_area: float | None = None,
    max_spacing: float | None = None,
) -> dict[str, Any]:
    """Place sprinkler heads individually on an even grid inside a room polygon (mm).

    Satisfies max area per head, max spacing between heads, and max wall distance
    (half the spacing, Table 4.4.7 / NFPA 13 / EN 12845).
    """
    from saengine.mep.rooms import room_grid

    default_cover, default_spacing = coverage(hazard, ceiling)
    cover = float(max_area if max_area is not None else default_cover)
    spacing = float(max_spacing if max_spacing is not None else default_spacing)
    area_m2 = outline.area / 1e6
    min_heads = max(1, math.ceil(area_m2 / cover - 1e-9)) if area_m2 > 0 else 1
    grid = room_grid(
        outline,
        min_count=min_heads,
        max_sx=spacing,
        max_sy=spacing,
        max_area_per_point=cover,
    )
    pts = grid["points"]
    return {
        "heads": pts,
        "count": len(pts),
        "nx": grid["nx"],
        "ny": grid["ny"],
        "sx": round(grid["sx"], 3),
        "sy": round(grid["sy"], 3),
        "coverage": cover,
        "maxSpacing": spacing,
        "perHead": round(area_m2 / len(pts), 2) if pts else cover,
    }


def layout_story_sprinklers(
    story: str,
    riser_xy: tuple[float, float],
    rooms_on_story: list[Any],
    floor_poly: Any,
    hazard: str,
    ceiling: str = "beams",
    material: str = "steel",
    *,
    head_offset: int = 1,
    pipe_offset: int = 1,
) -> dict[str, Any]:
    """Place individual sprinkler heads per room and route branch lines + cross main from the
    riser using RoomGraph, sizing every segment by the code pack's pipe schedule."""
    from saengine.mep.routing import RoomGraph, RoomPlace, path_length

    targets: list[tuple[str | None, Any]] = (
        [(r.id, r.net) for r in rooms_on_story]
        if rooms_on_story
        else ([(None, floor_poly)] if floor_poly is not None else [])
    )
    heads: list[dict[str, Any]] = []
    pipes: list[dict[str, Any]] = []
    h_idx = head_offset
    p_idx = pipe_offset

    # Build RoomGraph for cross main routing when architectural rooms exist
    graph: RoomGraph | None = None
    if rooms_on_story:
        places = [
            RoomPlace(r.id, r.face, bool(r.circulation or r.kind is not None))
            for r in rooms_on_story
        ]
        graph = RoomGraph(places)

    room_entries: list[dict[str, Any]] = []
    for room_id, poly in targets:
        placed = place_room_sprinklers(poly, hazard, ceiling)
        pts = placed["heads"]
        room_head_objs = []
        for x, y in pts:
            h_obj = {
                "id": f"SH-{h_idx}",
                "story": story,
                "room": room_id,
                "x": x,
                "y": y,
                "kFactor": T.K_FACTOR,
                "hazard": hazard,
                "sized": True,
            }
            h_idx += 1
            heads.append(h_obj)
            room_head_objs.append(h_obj)
        # Group into branch rows (by Y coordinate, left to right along X)
        rows_by_y: dict[float, list[dict[str, Any]]] = {}
        for h_obj in room_head_objs:
            rows_by_y.setdefault(h_obj["y"], []).append(h_obj)
        branch_rows = [
            sorted(row, key=lambda h: h["x"])
            for _, row in sorted(rows_by_y.items(), key=lambda kv: kv[0])
        ]
        # Connect each branch row to a room header spine (x_spine = min x or room entry)
        if branch_rows:
            x_spine = min(h["x"] for h in room_head_objs)
            # Route from riser via RoomGraph to room centre or x_spine
            route_pts = (
                graph.route(riser_xy, room_id)
                if (graph is not None and room_id is not None)
                else None
            )
            entry_pt = route_pts[-1] if route_pts else (x_spine, branch_rows[0][0]["y"])
            # Cross-main spine inside the room across the branch rows
            y_vals = [row[0]["y"] for row in branch_rows]
            # Branch lines per row
            for row in branch_rows:
                # Connect spine (x_spine, y) -> row[0] -> row[1] -> ...
                prev_pt = (x_spine, row[0]["y"])
                for idx_h, h_obj in enumerate(row):
                    downstream = len(row) - idx_h
                    cur_pt = (h_obj["x"], h_obj["y"])
                    if math.hypot(cur_pt[0] - prev_pt[0], cur_pt[1] - prev_pt[1]) > 1.0:
                        dia = schedule_size(downstream, hazard, material) or 25
                        pipes.append(
                            {
                                "id": f"SP-{p_idx}",
                                "story": story,
                                "kind": "branch",
                                "path": [list(prev_pt), list(cur_pt)],
                                "diameter": dia,
                                "heads": downstream,
                                "sized": True,
                            }
                        )
                        p_idx += 1
                    prev_pt = cur_pt
            # Spine segments along the room connecting branch take-offs
            if len(y_vals) >= 2:
                cum_heads = len(room_head_objs)
                for k in range(len(branch_rows) - 1):
                    dia = schedule_size(cum_heads, hazard, material) or 32
                    pipes.append(
                        {
                            "id": f"SP-{p_idx}",
                            "story": story,
                            "kind": "crossMain",
                            "path": [
                                [x_spine, branch_rows[k][0]["y"]],
                                [x_spine, branch_rows[k + 1][0]["y"]],
                            ],
                            "diameter": dia,
                            "heads": cum_heads,
                            "sized": True,
                        }
                    )
                    p_idx += 1
                    cum_heads -= len(branch_rows[k])
            room_entries.append(
                {
                    "room": room_id,
                    "heads": len(room_head_objs),
                    "entry": (x_spine, branch_rows[0][0]["y"]),
                    "route": route_pts or [riser_xy, entry_pt, (x_spine, branch_rows[0][0]["y"])],
                }
            )

    # Cross main feed from riser to each room entry
    total_heads = len(heads)
    if room_entries:
        # Order rooms nearest to farthest from riser, feed as a tree/header
        remaining = total_heads
        for rm in room_entries:
            pts = list(rm["route"])
            if math.hypot(pts[-1][0] - rm["entry"][0], pts[-1][1] - rm["entry"][1]) > 1.0:
                pts.append(rm["entry"])
            if len(pts) >= 2 and path_length(pts) > 1.0:
                dia = schedule_size(remaining, hazard, material) or 50
                pipes.append(
                    {
                        "id": f"SP-{p_idx}",
                        "story": story,
                        "kind": "crossMain",
                        "path": [[round(x, 1), round(y, 1)] for x, y in pts],
                        "diameter": dia,
                        "heads": remaining,
                        "sized": True,
                    }
                )
                p_idx += 1
            remaining = max(1, remaining - rm["heads"])

    return {
        "story": story,
        "heads": heads,
        "pipes": pipes,
        "headCount": len(heads),
        "mainSize": schedule_size(len(heads), hazard, material) if heads else None,
        "crossMainLengthM": round(
            sum(path_length(p["path"]) for p in pipes if p["kind"] == "crossMain") / 1000.0, 2
        ),
        "branchLengthM": round(
            sum(path_length(p["path"]) for p in pipes if p["kind"] != "crossMain") / 1000.0, 2
        ),
    }

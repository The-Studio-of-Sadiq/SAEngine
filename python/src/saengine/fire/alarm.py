"""Fire alarm device layout and battery calculation (NFPA 72 / BS 5839-1).

Places smoke and heat detectors per room by room use, manual call points at exits, sounders,
and a fire alarm control panel, and sizes the standby battery in Ah:
    C = (I_standby * T_standby_h + I_alarm * T_alarm_h) * ageing_factor.
"""

from __future__ import annotations

import math
import re
from typing import Any

from shapely.geometry import Point, box

from saengine.fire import tables as T
from saengine.mep import code_pack
from saengine.mep.rooms import room_grid


def _alarm_table() -> Any:
    table = T.ALARM
    if table is None:
        raise ValueError(code_pack.not_covered("Fire alarm device layout and battery sizing"))
    return table


def detector_kind(room_name: str, room_use: str | None = None) -> str:
    """Choose 'heat' or 'smoke' detector based on room name and occupancy use."""
    table = _alarm_table()
    text = f"{room_name} {room_use or ''}".lower()
    for token in table.heatRoomUses:
        if re.search(rf"(?<![a-z]){re.escape(token.lower())}(?![a-z])", text):
            return "heat"
    return "smoke"


def battery_calculation(
    standby_amps: float,
    alarm_amps: float,
    *,
    standby_hours: float | None = None,
    alarm_minutes: float | None = None,
    ageing_factor: float | None = None,
) -> dict[str, Any]:
    """Battery capacity [Ah] = (I_standby * T_standby + I_alarm * T_alarm) * ageing_factor."""
    table = _alarm_table()
    t_standby = float(standby_hours if standby_hours is not None else table.standbyHours)
    t_alarm_min = float(alarm_minutes if alarm_minutes is not None else table.alarmMinutes)
    t_alarm_h = t_alarm_min / 60.0
    factor = float(ageing_factor if ageing_factor is not None else table.ageingFactor)
    standby_ah = standby_amps * t_standby
    alarm_ah = alarm_amps * t_alarm_h
    unfactored = standby_ah + alarm_ah
    required = unfactored * factor
    recommended = next(
        (float(s) for s in sorted(table.batterySizesAh) if s >= required - 1e-9),
        float(math.ceil(required)),
    )
    return {
        "standbyAmps": round(standby_amps, 4),
        "standbyHours": t_standby,
        "standbyAh": round(standby_ah, 3),
        "alarmAmps": round(alarm_amps, 4),
        "alarmMinutes": t_alarm_min,
        "alarmHours": round(t_alarm_h, 4),
        "alarmAh": round(alarm_ah, 3),
        "unfactoredAh": round(unfactored, 3),
        "ageingFactor": factor,
        "requiredAh": round(required, 2),
        "recommendedAh": recommended,
    }


def _exit_points(story: str, arch: Any, outline: Any) -> list[tuple[float, float]]:
    """Find exit/door points on ``story`` from architecture doors, or boundary fallback."""
    pts: list[tuple[float, float]] = []
    if arch is not None and getattr(arch, "doors", None):
        walls = {w.id: w for w in getattr(arch, "walls", []) if w.base == story}
        for door in arch.doors:
            wall = walls.get(door.wall)
            if wall is None or len(wall.path) < 2:
                continue
            # Position along wall path
            x1, y1 = wall.path[0]
            x2, y2 = wall.path[-1]
            length = math.hypot(x2 - x1, y2 - y1) or 1.0
            t = min(max(door.offset / length, 0.0), 1.0)
            pts.append((round(x1 + (x2 - x1) * t, 1), round(y1 + (y2 - y1) * t, 1)))
    if not pts and outline is not None:
        minx, miny, maxx, _maxy = outline.bounds
        pts.append((round((minx + maxx) / 2, 1), round(miny + 200.0, 1)))
    return pts


def alarm_layout(
    mep: Any,
    building: Any = None,
    rooms: Any = None,
    arch: Any = None,
    *,
    stories: list[dict[str, Any]] | None = None,
    automatic: bool = True,
    manual: bool = True,
) -> dict[str, Any]:
    """Lay out fire alarm devices (detectors, MCPs, sounders, panel) and compute battery Ah.

    If ``mep.fire.alarmDevices`` already contains devices, uses them for the battery calc;
    otherwise proposes devices from the rooms / story footprints.
    """
    table = _alarm_table()
    fire = getattr(mep, "fire", None)
    settings = getattr(fire, "alarm", None) if fire is not None else None
    existing = list(getattr(fire, "alarmDevices", None) or [])

    devices: list[dict[str, Any]] = []
    if existing:
        devices = [d.model_dump(mode="json") for d in existing]
    elif manual or automatic:
        idx = 1
        story_list = [r["story"] for r in (stories or [])]
        if not story_list and rooms is not None:
            story_list = list(rooms.stories)
        elif not story_list and building is not None and building.known:
            order = building.ordered()
            story_list = order[:-1] if len(order) > 1 else order

        for i_story, story_id in enumerate(story_list):
            zone = f"Z{i_story + 1}"
            story_rooms = rooms.story(story_id) if rooms is not None else None
            floor_poly = (
                building.roof(story_id) if building is not None and building.known else None
            )
            if floor_poly is None and stories:
                row = next((r for r in stories if r["story"] == story_id), None)
                if row and row.get("area"):
                    side = math.sqrt(row["area"]) * 1000.0
                    floor_poly = box(0.0, 0.0, side, side)

            # Detectors
            if automatic:
                if story_rooms is not None and story_rooms.rooms:
                    for room in story_rooms.rooms:
                        kind = detector_kind(room.name, room.use)
                        spec = table.detectors[kind]
                        dev_kind = "heatDetector" if kind == "heat" else "smokeDetector"
                        grid = room_grid(
                            room.net,
                            min_count=max(1, math.ceil(room.area / spec.maxArea - 1e-9)),
                            max_sx=spec.maxSpacing,
                            max_sy=spec.maxSpacing,
                            max_area_per_point=spec.maxArea,
                        )
                        for x, y in grid["points"]:
                            devices.append(
                                {
                                    "id": f"FA-{idx}",
                                    "kind": dev_kind,
                                    "story": story_id,
                                    "room": room.id,
                                    "x": x,
                                    "y": y,
                                    "zone": zone,
                                    "sized": True,
                                }
                            )
                            idx += 1
                elif floor_poly is not None:
                    spec = table.detectors["smoke"]
                    area_m2 = floor_poly.area / 1e6
                    grid = room_grid(
                        floor_poly,
                        min_count=max(1, math.ceil(area_m2 / spec.maxArea - 1e-9)),
                        max_sx=spec.maxSpacing,
                        max_sy=spec.maxSpacing,
                        max_area_per_point=spec.maxArea,
                    )
                    for x, y in grid["points"]:
                        devices.append(
                            {
                                "id": f"FA-{idx}",
                                "kind": "smokeDetector",
                                "story": story_id,
                                "room": None,
                                "x": x,
                                "y": y,
                                "zone": zone,
                                "sized": True,
                            }
                        )
                        idx += 1

            # Manual call points at exits
            exits = _exit_points(story_id, arch, floor_poly)
            area_m2 = floor_poly.area / 1e6 if floor_poly is not None else 0.0
            need_mcp = max(1, math.ceil(area_m2 / T.CALL_POINT_AREA - 1e-9)) if area_m2 else 1
            for k in range(max(len(exits), need_mcp)):
                px, py = exits[k % len(exits)] if exits else (0.0, 0.0)
                devices.append(
                    {
                        "id": f"FA-{idx}",
                        "kind": "callPoint",
                        "story": story_id,
                        "room": None,
                        "x": px,
                        "y": py,
                        "zone": zone,
                        "sized": True,
                    }
                )
                idx += 1

            # Sounders
            s_area = table.sounder.maxArea or 200.0
            need_snd = max(1, math.ceil(area_m2 / s_area - 1e-9)) if area_m2 else 1
            if story_rooms is not None and story_rooms.rooms:
                corridors = [r for r in story_rooms.rooms if r.circulation]
                anchors = [r.net.representative_point() for r in corridors] or [
                    story_rooms.rooms[0].net.representative_point()
                ]
            elif floor_poly is not None:
                anchors = [floor_poly.representative_point()]
            else:
                anchors = [Point(0.0, 0.0)]
            for k in range(need_snd):
                pt = anchors[k % len(anchors)]
                devices.append(
                    {
                        "id": f"FA-{idx}",
                        "kind": "sounder",
                        "story": story_id,
                        "room": None,
                        "x": round(pt.x, 1),
                        "y": round(pt.y, 1),
                        "zone": zone,
                        "sized": True,
                    }
                )
                idx += 1

        # Fire Alarm Control Panel on ground / lowest story
        if story_list:
            first_story = story_list[0]
            poly0 = building.roof(first_story) if building is not None and building.known else None
            pt0 = poly0.representative_point() if poly0 is not None else Point(0.0, 0.0)
            devices.append(
                {
                    "id": "FACP-1",
                    "kind": "panel",
                    "story": first_story,
                    "room": None,
                    "x": round(pt0.x, 1),
                    "y": round(pt0.y, 1),
                    "zone": "MAIN",
                    "sized": True,
                }
            )

    counts = {
        "smokeDetector": sum(1 for d in devices if d["kind"] == "smokeDetector"),
        "heatDetector": sum(1 for d in devices if d["kind"] == "heatDetector"),
        "callPoint": sum(1 for d in devices if d["kind"] == "callPoint"),
        "sounder": sum(1 for d in devices if d["kind"] == "sounder"),
        "panel": sum(1 for d in devices if d["kind"] == "panel"),
    }
    panel_standby = (
        settings.panelStandbyA
        if settings and settings.panelStandbyA is not None
        else table.panel.standbyA
    )
    panel_alarm = (
        settings.panelAlarmA
        if settings and settings.panelAlarmA is not None
        else table.panel.alarmA
    )
    n_panels = max(counts["panel"], 1) if devices else 0
    standby_a = (
        n_panels * panel_standby
        + (
            counts["smokeDetector"] * table.detectors["smoke"].standbyMa
            + counts["heatDetector"] * table.detectors["heat"].standbyMa
            + counts["callPoint"] * table.callPoint.standbyMa
            + counts["sounder"] * table.sounder.standbyMa
        )
        / 1000.0
    )
    alarm_a = (
        n_panels * panel_alarm
        + (
            counts["smokeDetector"] * table.detectors["smoke"].alarmMa
            + counts["heatDetector"] * table.detectors["heat"].alarmMa
            + counts["callPoint"] * table.callPoint.alarmMa
            + counts["sounder"] * table.sounder.alarmMa
        )
        / 1000.0
    )
    battery = (
        battery_calculation(
            standby_a,
            alarm_a,
            standby_hours=settings.standbyHours if settings else None,
            alarm_minutes=settings.alarmMinutes if settings else None,
            ageing_factor=settings.ageingFactor if settings else None,
        )
        if devices
        else None
    )
    return {
        "devices": devices,
        "counts": counts,
        "battery": battery,
    }

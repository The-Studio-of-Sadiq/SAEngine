"""An estimate of each room's average daylight factor (alpha 9 L11).

The average daylight factor of a side-lit room, in the form of BRE BR 209 Appendix C / CIBSE LG10
(Littlefair):

    DF = T · Aw · θ · M / (A · (1 − R²))   [%]

with T the diffuse transmittance of the glazing, Aw the net glazed area of the windows serving
the room [m²] (the windows' openings less the frame), θ the visible sky angle at the window [°]
(90 for an unobstructed vertical window, less the obstruction angle seen from its centre), M the
maintenance factor, A the room's total internal surface area (floor, ceiling and walls) [m²] and
R the area-weighted mean reflectance of those surfaces. The values of T, M, R and the frame share
are SAEngine practice defaults (``data/environment-defaults.json``), editable per project in
``06 BIM/environment.json``; no code target is applied (the engineer compares the DF with the
target of the code or standard the project follows).

Rooms come from the architecture (``05 Floor Plan/architecture.json``): a room's net floor from
its walls (:func:`saengine.library.architecture.room_boundary`), its height to the level above,
and the windows in the walls bounding it. The obstruction angle is found by casting rays from the
window's centre, out of the room, at rising angles against the massing (:mod:`.solar`).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from saengine.environment.solar import Massing


def average_daylight_factor(
    glazed: float, sky_angle: float, surface: float, t: float, m: float, r: float
) -> float:
    """DF [%] of the formula above (areas in m², the angle in degrees)."""
    if surface <= 0 or r >= 1:
        return 0.0
    return t * glazed * sky_angle * m / (surface * (1 - r * r))


def obstruction_angle(
    massing: Massing, origin: np.ndarray, outward: tuple[float, float], step: float = 5.0
) -> float:
    """The lowest angle [°] above the horizontal, looking ``outward`` from ``origin``, at which
    the view is clear of the massing (0 when unobstructed)."""
    nx, ny = outward
    angle = 0.0
    while angle < 90.0:
        a = math.radians(angle)
        d = np.array([nx * math.cos(a), ny * math.cos(a), math.sin(a)])
        if not massing.blocked(origin[None, :], d)[0]:
            return angle
        angle += step
    return 90.0


def room_daylight(
    architecture: Any,
    elevations: dict[str, float],
    massing: Massing,
    values: dict[str, float],
) -> list[dict[str, Any]]:
    """``[{room, name, story, floorArea, windowArea, skyAngle, df, windows, notes}]`` per room."""
    from shapely.geometry import Point

    from saengine.library.architecture import (
        centre_line,
        opening_size,
        point_along,
        room_boundary,
    )

    t, m, r = values["transmittance"], values["maintenance"], values["reflectance"]
    frame = values["frameShare"]
    wall_types = {w.id: w for w in architecture.wallTypes}
    walls = {w.id: w for w in architecture.walls}
    levels = sorted(set(elevations.values()))
    out = []
    for room in architecture.rooms:
        notes: list[str] = []
        found = room_boundary(architecture, room, elevations)
        if found is None or room.story not in elevations:
            out.append({"room": room.id, "name": room.name, "story": room.story,
                        "notes": ["not enclosed: no daylight factor"]})  # fmt: skip
            continue
        _, net = found
        z0 = elevations[room.story]
        above = [z for z in levels if z > z0 + 1]
        height = (above[0] - z0) if above else 3000.0
        if not above:
            notes.append("no level above: a 3 m room height is assumed")
        floor = net.area * 1e-6
        surface = 2 * floor + net.length * 1e-3 * height * 1e-3
        glazed = 0.0
        angles: list[tuple[float, float]] = []
        windows = []
        for window in architecture.windows:
            wall = walls.get(window.wall)
            if wall is None:
                continue
            wall_type = wall_types.get(wall.type)
            if wall_type is None:
                continue
            centre = centre_line(wall, wall_type)
            try:
                (x, y), (dx, dy) = point_along(centre, window.offset)
            except (ValueError, IndexError, TypeError):
                continue
            if net.distance(Point(x, y)) > wall_type.thickness / 2 + 50:
                continue  # not in a wall of this room
            width, h, sill = opening_size(architecture, window)
            area = width * h * 1e-6 * (1 - frame)
            length = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / length, dx / length
            reach = wall_type.thickness / 2 + 300
            if net.contains(Point(x + nx * reach, y + ny * reach)):
                nx, ny = -nx, -ny  # point out of the room
            origin = np.array([x + nx * reach, y + ny * reach, z0 + sill + h / 2])
            obstruction = obstruction_angle(massing, origin, (nx, ny))
            theta = 90.0 - obstruction
            glazed += area
            angles.append((area, theta))
            windows.append(
                {"window": window.id, "glazedArea": round(area, 3), "skyAngle": round(theta, 1)}
            )
        if not windows:
            out.append({"room": room.id, "name": room.name, "story": room.story,
                        "floorArea": round(floor, 2), "df": 0.0, "windows": [],
                        "notes": [*notes, "no window: no daylight from side windows"]})  # fmt: skip
            continue
        theta = sum(a * th for a, th in angles) / glazed if glazed > 0 else 0.0
        df = average_daylight_factor(glazed, theta, surface, t, m, r)
        out.append(
            {
                "room": room.id,
                "name": room.name,
                "story": room.story,
                "floorArea": round(floor, 2),
                "surfaceArea": round(surface, 2),
                "windowArea": round(glazed, 3),
                "skyAngle": round(theta, 1),
                "df": round(df, 2),
                "windows": windows,
                "notes": notes,
            }
        )
    return out

"""The static eccentricity of a storey and the design eccentricity a code pack may ask for.

Some codes design the accidental torsion of the equivalent static method for a design
eccentricity ``ed = a es + accidental`` (and ``es - accidental``), es the static eccentricity
between the centre of mass and the centre of rigidity of the storey (IS 1893 (Part 1):2016
7.8.2: a = 1.5). The 3D analysis model already carries es, so the static cases add only what
the design eccentricity has more: ``(a - 1) es`` on the side where it adds to the accidental
share, nothing on the other (:func:`extra`). The pack picks it with ``seismic.
designEccentricity`` (``staticAmplification``); without it nothing changes.

The centre of rigidity of a storey is estimated from the vertical members that reach the level
from below: each column and structural wall weighted by its flexural stiffness along the
shaking, ``b d³ / 12`` of its plan rectangle (a wall: its thickness by its length), the
storey height common to all (SAEngine practice: a plan estimate; the code defines CR but gives
no method). The centre of mass is the level's nodal mass shares.

Units: plan coordinates in m; the elements in mm.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context

MM = 1e-3


def rule() -> Any | None:
    """The pack's ``seismic.designEccentricity`` (None: the accidental share alone)."""
    return getattr(code_context.table("seismic"), "designEccentricity", None)


def _column_rectangle(object_type: Any, rotation: float) -> tuple[float, float] | None:
    """(extent along X, along Y) [m] of a column's profile, turned by its rotation."""
    profile = getattr(object_type, "profile", None)
    if profile is None:
        return None
    try:
        from saengine.library.sections import profile_geometry

        xmin, xmax, ymin, ymax = profile_geometry(profile).calculate_extents()
    except Exception:  # noqa: BLE001 - a profile without geometry is left out
        return None
    w, d = float(xmax - xmin) * MM, float(ymax - ymin) * MM
    turn = math.radians(rotation or 0.0)
    c, s = abs(math.cos(turn)), abs(math.sin(turn))
    return w * c + d * s, w * s + d * c


def members(
    elements: list[Any], types: dict[str, Any], level_mm: float
) -> list[tuple[float, float, float, float]]:
    """Per vertical member reaching ``level_mm`` from below: (x, y [m], kx, ky), k the
    flexural stiffness proxy along X and along Y [m⁴]."""
    from saengine.library.bim import ColumnElement, WallElement

    out = []
    for e in elements:
        kind = types.get(e.type)
        if isinstance(e, ColumnElement):
            if not (e.bottom < level_mm - 1.0 and e.top >= level_mm - 1.0):
                continue
            rect = _column_rectangle(kind, e.rotation)
            if rect is None:
                continue
            ax, ay = rect
            out.append((e.position[0] * MM, e.position[1] * MM, ay * ax**3 / 12, ax * ay**3 / 12))
        elif isinstance(e, WallElement) and getattr(kind, "structural", False):
            if not (e.bottom < level_mm - 1.0 and e.top >= level_mm - 1.0):
                continue
            t = float(getattr(kind, "thickness", 0.0) or 0.0) * MM
            dx, dy = (e.end[0] - e.start[0]) * MM, (e.end[1] - e.start[1]) * MM
            length = math.hypot(dx, dy)
            if t <= 0 or length <= 0:
                continue
            c, s = abs(dx) / length, abs(dy) / length
            strong, weak = t * length**3 / 12, length * t**3 / 12
            out.append(
                (
                    (e.start[0] + e.end[0]) / 2 * MM,
                    (e.start[1] + e.end[1]) / 2 * MM,
                    strong * c + weak * s,
                    strong * s + weak * c,
                )
            )
    return out


def static_eccentricity(
    stiff: list[tuple[float, float, float, float]],
    masses: list[tuple[float, float, float]],
) -> tuple[float, float] | None:
    """(es across X shaking (CM - CR along Y), es across Y shaking (along X)) [m] from the
    members' (x, y, kx, ky) and the level's (x, y, mass share); None without either."""
    total = sum(m for _, _, m in masses)
    kx = sum(k for _, _, k, _ in stiff)
    ky = sum(k for _, _, _, k in stiff)
    if total <= 0 or kx <= 0 or ky <= 0:
        return None
    cm_x = sum(x * m for x, _, m in masses) / total
    cm_y = sum(y * m for _, y, m in masses) / total
    cr_y = sum(y * k for _, y, k, _ in stiff) / kx  # X shaking resisted at its y
    cr_x = sum(x * k for x, _, _, k in stiff) / ky
    return cm_y - cr_y, cm_x - cr_x


def extra(es: float, sign: float, amplification: float) -> float:
    """The design eccentricity beyond the accidental share [m] for the static case of sign
    ``sign`` (+1 / -1 along the accidental shift): (a - 1) es where the case shifts the mass
    the way es lies, else nothing."""
    return (amplification - 1.0) * es if sign * es > 0 else 0.0

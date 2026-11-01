"""Wind on open structures: the members of a special structure loaded by force coefficients.

Special structures (Part 5: trusses, space frames, portal frames, towers, canopy frames) have no
floors to take storey wind forces, so their wind is applied member by member as for "other
structures" (BNBC 2020 Part 6 Sec 2.4, design wind loads on other structures, which follows
ASCE 7-05 Sec 6.5.15; the coefficients are the code pack's ``wind.openStructures``):

    F = qz · G · Cf · Af                                    (ASCE 7-05 Eq 6-28)

- qz, the velocity pressure at the height z of each member's middle (BNBC Sec 2.4.6,
  :func:`saengine.fem.loads.velocity_pressure`), G the gust factor of a rigid structure;
- Af, the member's area projected on a plane normal to the wind: its outer width (the larger
  outer dimension of its profile, so either way it faces the wind) times its length times
  sin φ, φ the angle between the member and the wind;
- Cf of an open framework by its solidity ratio ε (solid area / gross area of the face; flat
  or rounded members, Figure 6-22), or of a trussed tower's face (square or triangular,
  Figure 6-23, with the factor for rounded members and the diagonal wind on a square tower).

Each member then carries a uniform load w = qz·G·Cf·d·sin φ along the wind (in N/m of its
length). ε is taken from the settings or computed in each direction from the model: the sum of
the members' projected areas over the area of their projected outline (its bounding rectangle
on the plane normal to the wind), capped at the table's last row. For a tower the coefficient
is that of one face; the load is shared by all the members in the wind, so it is scaled by the
face's share of their projected area, taken as one half (exact for a square tower, whose two
faces both stand normal to the wind; an assumption for a triangular one).

Not covered here: the net pressures on free roofs of open buildings (the canopy's cladding),
the pressures on clad sheds (walls and roofs with internal pressure), shielding of one frame by
another (every member is loaded fully: conservative for a row of frames), and vortex shedding.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: ft·√psf to m·√Pa (the D√qz limit of the rounded-member coefficients).
FT_SQRT_PSF = 0.3048 * math.sqrt(47.880259)
#: Directions of the wind cases.
DIRECTIONS = {"WX": np.array([1.0, 0.0, 0.0]), "WY": np.array([0.0, 1.0, 0.0])}
#: A trussed tower face's share of the projected area of all the members in the wind.
TOWER_FACE_SHARE = 0.5


def lattice_cf(table: Any, solidity: float, rounded: bool = False, d_sqrt_qz: float = 0.0) -> float:
    """Cf of an open sign or lattice framework (Figure 6-22): by the solidity ratio ε, flat or
    rounded members; for rounded ones by D√qz [m·√Pa] against the table's limit."""
    rows = sorted(table.lattice, key=lambda r: r.solidityMax)
    row = next((r for r in rows if solidity < r.solidityMax), rows[-1])
    if not rounded:
        return float(row.flat)
    small = d_sqrt_qz <= table.roundLimit * FT_SQRT_PSF
    return float(row.roundSmall if small else row.roundLarge)


def tower_cf(
    table: Any, solidity: float, shape: str, rounded: bool = False, diagonal: bool = False
) -> float:
    """Cf of a trussed tower's face (Figure 6-23): a·ε² + b·ε + c for a square or triangular
    cross-section; × (0.51ε² + 0.57, at most 1) for rounded members; a square tower's wind on
    the diagonal × (1 + 0.75ε, at most 1.2)."""
    coeff = table.squareTower if shape == "square" else table.triangularTower
    e = solidity
    cf = coeff.a * e * e + coeff.b * e + coeff.c
    if rounded:
        r = table.roundTower
        cf *= min(1.0, r.a * e * e + r.b * e + r.c)
    if diagonal and shape == "square":
        k, cap = table.diagonalFactor
        cf *= min(cap, 1 + k * e)
    return float(cf)


def outer_width(profile: Any) -> float:
    """The larger outer dimension of a member's profile [mm] (0 when unknown: a designed
    section)."""
    if profile is None:
        return 0.0
    radius = getattr(profile, "radius", None)
    if radius:
        return 2.0 * float(radius)
    sizes = [
        getattr(profile, name, None)
        for name in (
            "xDim",
            "yDim",
            "overallDepth",
            "overallWidth",
            "depth",
            "width",
            "flangeWidth",
        )
    ]
    return float(max((s for s in sizes if s), default=0.0))


@dataclass
class WindMember:
    """A member as the wind sees it: its ends [m] and outer width [m]."""

    index: int
    start: np.ndarray
    end: np.ndarray
    width: float

    @property
    def length(self) -> float:
        return float(np.linalg.norm(self.end - self.start))

    def sin_to(self, wind: np.ndarray) -> float:
        """sin of the angle between the member and the wind."""
        axis = (self.end - self.start) / max(self.length, 1e-12)
        return float(np.linalg.norm(np.cross(axis, wind)))


def projected_area(members: Iterable[WindMember], wind: np.ndarray) -> float:
    """Σ width·length·sin φ of the members [m²]."""
    return float(sum(m.width * m.length * m.sin_to(wind) for m in members))


def outline_area(members: Iterable[WindMember], wind: np.ndarray) -> float:
    """Area of the bounding rectangle of the members' ends projected on the vertical plane
    normal to the horizontal wind ``wind`` [m²]."""
    across = np.array([-wind[1], wind[0], 0.0])
    points = [p for m in members for p in (m.start, m.end)]
    if not points:
        return 0.0
    u = np.array([float(p @ across) for p in points])
    z = np.array([float(p[2]) for p in points])
    return float((u.max() - u.min()) * (z.max() - z.min()))


@dataclass
class OpenWind:
    """The member loads of the wind cases and how they were found."""

    #: case -> [(member index, global load vector N/m)]
    loads: dict[str, list[tuple[int, np.ndarray]]] = field(default_factory=dict)
    #: case -> {"solidity", "Cf", "force_kN", "area_m2"}
    summary: dict[str, dict[str, float]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def open_structure_wind(
    members: list[WindMember],
    qz_of: Any,
    gust: float,
    table: Any,
    form: str = "lattice",
    solidity: float | None = None,
    rounded: bool = False,
) -> OpenWind:
    """The uniform member loads of the wind cases WX and WY (+X and +Y; the combinations take
    them with ±). ``qz_of(z)``: the velocity pressure [Pa] at height z [m]."""
    result = OpenWind()
    last = max(r.solidityMax for r in table.lattice)
    for case, wind in DIRECTIONS.items():
        facing = [m for m in members if m.sin_to(wind) > 1e-6 and m.width > 0]
        if not facing:
            continue
        af = projected_area(facing, wind)
        gross = outline_area(facing, wind)
        eps = solidity if solidity is not None else (min(1.0, af / gross) if gross > 0 else last)
        if form == "lattice" and eps > last:
            result.notes.append(
                f"{case}: solidity ratio {eps:.2f} above the open framework range ({last:g}); "
                f"Cf taken at its last row"
            )
        share = 1.0
        if form in ("squareTower", "triangularTower"):
            shape = "square" if form == "squareTower" else "triangular"
            cf_tower = tower_cf(table, min(eps, 1.0), shape, rounded)
            share = TOWER_FACE_SHARE
            result.notes.append(
                f"{case}: trussed tower Cf {cf_tower:.2f} of one face, shared by all the "
                f"members in the wind (× {share:g}, the face's assumed share of their area)"
            )
        total = 0.0
        loads = []
        cf_used: list[float] = []
        for m in facing:
            z = float(m.start[2] + m.end[2]) / 2
            qz = float(qz_of(max(z, 0.0)))
            if form == "lattice":
                cf = lattice_cf(table, eps, rounded, m.width * math.sqrt(max(qz, 0.0)))
            else:
                cf = cf_tower * share
            w = qz * gust * cf * m.width * m.sin_to(wind)  # N/m along the wind
            loads.append((m.index, wind * w))
            total += w * m.length
            cf_used.append(cf)
        result.loads[case] = loads
        result.summary[case] = {
            "solidity": round(eps, 3),
            "Cf": round(max(cf_used), 3),
            "area_m2": round(af, 2),
            "force_kN": round(total / 1e3, 2),
        }
    return result

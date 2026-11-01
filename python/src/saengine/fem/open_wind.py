"""Wind on open structures: the members of a special structure loaded by force coefficients.

Special structures (Part 5: trusses, space frames, portal frames, towers, canopy frames) have no
floors to take storey wind forces, so their wind is applied member by member as for "other
structures" (the default pack's Part 6 Sec 2.4.14; the coefficients are the code pack's
``wind.openStructures``, Figures 6.2.22-6.2.23, and ``wind.chimneys``, Figure 6.2.21):

    F = qz · G · Cf · Af                                    (Eq 6.2.30)

- qz, the velocity pressure at the height z of each member's middle (the default pack's Sec 2.4.6,
  :func:`saengine.fem.loads.velocity_pressure`), G the gust factor of a rigid structure;
- Af, the member's area projected on a plane normal to the wind: its outer width (the larger
  outer dimension of its profile, so either way it faces the wind) times its length times
  sin φ, φ the angle between the member and the wind;
- Cf of an open framework by its solidity ratio ε (solid area / gross area of the face; flat
  or rounded members, Figure 6.2.22), or of a trussed tower's face (square or triangular,
  Figure 6.2.23, with the factor for rounded members and the diagonal wind on a square tower),
  or of a chimney, tank or similar structure (form ``chimney``: Figure 6.2.21 by its
  cross-section and h/D, each member's width its D).

Further down: solid freestanding walls and signs (Sec 2.4.13, Figure 6.2.20,
:func:`solid_sign_wind`), chimneys and tanks (:func:`chimney_cf`) and rooftop equipment on low
buildings (Sec 2.4.15, :func:`rooftop_equipment_wind`).

Each member then carries a uniform load w = qz·G·Cf·d·sin φ along the wind (in N/m of its
length). ε is taken from the settings or computed in each direction from the model: the sum of
the members' projected areas over the area of their projected outline (its bounding rectangle
on the plane normal to the wind), capped at the table's last row. For a tower the coefficient
is that of one face; the load is shared by all the members in the wind, so it is scaled by the
face's share of their projected area, taken as one half (exact for a square tower, whose two
faces both stand normal to the wind; an assumption for a triangular one).

A clad special structure (a shed with its sheeting, a clad vault or dome: the wind settings'
form ``clad``) is a building instead: :func:`clad_structure_wind` below gives the pressures on
its panels (walls and roofs with internal pressure, the default pack's Part 6 Sec 2.4.11.2). An open
one (a canopy or free roof: form ``clad``, enclosure ``open``) takes the net pressures of free
roofs instead (:func:`free_roof_wind`, Sec 2.4.12).

Not covered here: fascia panels of free roofs as inverted parapets, shielding of one frame by
another (every member is loaded fully: conservative for a row of frames), and vortex shedding.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

import numpy as np

#: Directions of the wind cases.
DIRECTIONS = {"WX": np.array([1.0, 0.0, 0.0]), "WY": np.array([0.0, 1.0, 0.0])}
#: A trussed tower face's share of the projected area of all the members in the wind.
TOWER_FACE_SHARE = 0.5


def lattice_cf(table: Any, solidity: float, rounded: bool = False, d_sqrt_qz: float = 0.0) -> float:
    """Cf of an open sign or lattice framework (Figure 6.2.22): by the solidity ratio ε, flat or
    rounded members; for rounded ones by D√qz (D in m, qz in N/m²) against the table's limit."""
    rows = sorted(table.lattice, key=lambda r: r.solidityMax)
    row = next((r for r in rows if solidity < r.solidityMax), rows[-1])
    if not rounded:
        return float(row.flat)
    small = d_sqrt_qz <= table.roundLimit
    return float(row.roundSmall if small else row.roundLarge)


def tower_cf(
    table: Any, solidity: float, shape: str, rounded: bool = False, diagonal: bool = False
) -> float:
    """Cf of a trussed tower's face (Figure 6.2.23): a·ε² + b·ε + c for a square or triangular
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
    section: str = "square",
    surface: str = "all",
    chimneys: Any = None,
) -> OpenWind:
    """The uniform member loads of the wind cases WX and WY (+X and +Y; the combinations take
    them with ±). ``qz_of(z)``: the velocity pressure [Pa] at height z [m]. Form ``chimney``:
    every member takes Cf of the ``chimneys`` table (Figure 6.2.21) for ``section`` and
    ``surface``, its width D and the structure's height h."""
    if form == "chimney":
        return _chimney_structure_wind(members, qz_of, gust, chimneys, section, surface)
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


def _chimney_structure_wind(
    members: list[WindMember], qz_of: Any, gust: float, table: Any, section: str, surface: str
) -> OpenWind:
    """Form ``chimney`` of :func:`open_structure_wind`: w = qz·G·Cf·D·sin φ on each member, Cf
    of Figure 6.2.21 by h/D (h the structure's height, D the member's width) and, for a round
    section, D√qz."""
    result = OpenWind()
    if table is None:
        result.notes.append("the code pack has no force coefficients of chimneys and tanks")
        return result
    zs = [float(p[2]) for m in members for p in (m.start, m.end)]
    height = (max(zs) - min(zs)) if zs else 0.0
    for case, wind in DIRECTIONS.items():
        facing = [m for m in members if m.sin_to(wind) > 1e-6 and m.width > 0]
        if not facing:
            continue
        loads, total, cfs = [], 0.0, []
        for m in facing:
            z = float(m.start[2] + m.end[2]) / 2
            qz = float(qz_of(max(z, 0.0)))
            cf = chimney_cf(
                table, section, surface, height / m.width, m.width * math.sqrt(max(qz, 0.0))
            )
            w = qz * gust * cf * m.width * m.sin_to(wind)
            loads.append((m.index, wind * w))
            total += w * m.length
            cfs.append(cf)
        result.loads[case] = loads
        result.summary[case] = {
            "solidity": 1.0,
            "Cf": round(max(cfs), 3),
            "area_m2": round(projected_area(facing, wind), 2),
            "force_kN": round(total / 1e3, 2),
        }
    result.notes.append(
        f"chimney or tank ({section}, {surface} surface): Cf by h/D with h = {height:.2f} m "
        f"({table.source})"
    )
    return result


# ─────────────── other structures: chimneys, tanks, solid signs, rooftop equipment ───────────────


def chimney_cf(
    table: Any, section: str, surface: str = "all", h_over_d: float = 1.0, d_sqrt_qz: float = 0.0
) -> float:
    """Cf of a chimney, tank, rooftop equipment or similar structure (the default pack's Part 6 Figure
    6.2.21, the code pack's ``wind.chimneys``) of cross-section ``section`` (square, its wind on
    the diagonal squareDiagonal, polygonal: hexagonal or octagonal, round) by h/D (linear,
    note 2; held at the figure's ends). A round section takes the row of its ``surface`` when
    D√qz (D in m, qz in N/m²) is above the limit, else the one row of all surfaces."""
    if section == "round" and d_sqrt_qz <= table.roundLimit:
        row = next(r for r in table.rows if r.section == "round" and r.small)
    else:
        wanted = surface if section == "round" else "all"
        row = next(
            (r for r in table.rows if r.section == section and r.surface == wanted and not r.small),
            None,
        )
        if row is None:
            raise ValueError(f"no force coefficient for a {section} section, {surface} surface")
    return _lerp(h_over_d, list(table.hOverD), list(row.cf))


def _table_value(xs: list[float], ys: list[float | None], x: float) -> float | None:
    """Linear in ``xs`` where both neighbours have a value; the one that has one otherwise."""
    pairs = list(zip(xs, ys, strict=True))
    if x <= xs[0]:
        return ys[0]
    for (x0, y0), (x1, y1) in pairwise(pairs):
        if x <= x1:
            if y0 is None or y1 is None:
                return y1 if y0 is None else y0
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return ys[-1]


def solid_sign_cf(table: Any, s_over_h: float, b_over_s: float) -> float:
    """Cf of cases A and B of a solid freestanding wall or sign (the default pack's Part 6 Figure 6.2.20,
    the code pack's ``wind.solidSigns``) by its clearance ratio s/h and aspect ratio B/s, linear
    in both (note 5) and held at the figure's ends."""
    order = sorted(range(len(table.clearance)), key=lambda i: table.clearance[i])
    rows = [table.caseAB[i] for i in order]
    clearances = [table.clearance[i] for i in order]
    by_row = [_lerp(b_over_s, list(table.aspect), list(r)) for r in rows]
    return _lerp(s_over_h, clearances, by_row)


def solid_sign_case_c(
    table: Any, s_over_h: float, b_over_s: float, return_corner: float | None = None
) -> list[dict[str, float]]:
    """Case C of a long solid wall or sign (B/s ≥ 2, Figure 6.2.20): its regions by distance
    from the windward edge in multiples of s, ``[{"from_s", "to_s", "Cf"}]``, each Cf × (1.8 −
    s/h) when s/h > 0.8 (note 4) and the first × the return-corner factor of Lr/s
    ``return_corner`` where the figure marks it (B/s ≥ 5; none below the figure's least Lr/s).
    Empty below the table's least B/s."""
    c = table.caseC
    if b_over_s < c.minAspect:
        return []
    factor = (c.reductionConstant - s_over_h) if s_over_h > c.reductionAbove else 1.0
    out = []
    start = 0.0
    for i, region in enumerate(c.regions):
        if start >= b_over_s:
            break
        end = b_over_s if region.end is None else min(region.end, b_over_s)
        cf = _table_value(list(c.aspect), list(region.cf), b_over_s)
        if cf is not None:
            value = cf * factor
            corner = table.returnCorner
            if i == 0 and return_corner and corner and b_over_s >= corner.fromAspect:
                points = [tuple(p) for p in corner.factors]
                if return_corner >= points[0][0]:
                    value *= _lerp(return_corner, [p[0] for p in points], [p[1] for p in points])
            out.append({"from_s": start, "to_s": end, "Cf": round(value, 4)})
        start = end if region.end is not None else b_over_s
    return out


def solid_sign_wind(
    qh: float,
    gust: float,
    width: float,
    depth: float,
    height: float,
    solidity: float = 1.0,
    return_corner: float | None = None,
    open_table: Any = None,
) -> dict[str, Any]:
    """The design wind force on a solid freestanding wall or sign (the default pack's Part 6 Sec 2.4.13,
    Eq 6.2.29: F = qh·G·Cf·As, Figure 6.2.20) of ``width`` B, ``depth`` s (its vertical
    dimension) and top at ``height`` h [m], ``qh`` the velocity pressure at h [kN/m²]:

    - cases A and B: F through the geometric centre, and 0.2·B toward the windward edge (for
      s/h = 1 both 0.05·s above the centre);
    - case C (B/s ≥ 2): the force of each region at its centre;
    - a sign with openings (``solidity`` ε below 1) takes Cf × (1 − (1 − ε)^1.5) (note 2); one
      with 30 % or more open (ε ≤ 0.7) is an open sign: Figure 6.2.22's flat-member Cf on
      its solid area (``open_table``, the pack's ``openStructures``)."""
    table = _wind_block("solidSigns")
    s_over_h, b_over_s = depth / height, width / depth
    gross = width * depth
    lift = table.fullHeightLift * depth if s_over_h >= 0.999 else 0.0
    centre = height - depth / 2 + lift
    notes: list[str] = []
    if solidity <= table.solidMin and open_table is not None:
        cf = lattice_cf(open_table, solidity)
        area = gross * solidity
        force = qh * gust * cf * area
        notes.append(
            f"ε = {solidity:g} ≤ {table.solidMin:g}: an open sign, Cf of open signs on the solid "
            f"area ({open_table.source})"
        )
        return {
            "kind": "open",
            "s_h": s_over_h,
            "B_s": b_over_s,
            "Cf": cf,
            "As_m2": area,
            "cases": {"A": {"F_kN": force, "z_m": centre, "offset_m": 0.0}},
            "caseC": [],
            "notes": notes,
        }
    reduction = 1.0
    if solidity < 1.0:
        reduction = 1.0 - (1.0 - solidity) ** table.openingExponent
        notes.append(f"openings: Cf × {reduction:.3f} (1 − (1 − ε)^{table.openingExponent:g})")
    cf = solid_sign_cf(table, s_over_h, b_over_s) * reduction
    force = qh * gust * cf * gross
    cases = {
        "A": {"F_kN": force, "z_m": centre, "offset_m": 0.0},
        "B": {"F_kN": force, "z_m": centre, "offset_m": table.caseBOffset * width},
    }
    regions = []
    for r in solid_sign_case_c(table, s_over_h, b_over_s, return_corner):
        length = (r["to_s"] - r["from_s"]) * depth
        cf_r = r["Cf"] * reduction
        regions.append(
            {
                **r,
                "Cf": cf_r,
                "F_kN": qh * gust * cf_r * length * depth,
                "x_m": (r["from_s"] + r["to_s"]) / 2 * depth,
                "z_m": centre,
            }
        )
    return {
        "kind": "solid",
        "s_h": s_over_h,
        "B_s": b_over_s,
        "Cf": cf,
        "As_m2": gross,
        "cases": cases,
        "caseC": regions,
        "notes": notes,
    }


def _wind_block(name: str) -> Any:
    """The code pack's ``wind.<name>`` block; ValueError when the pack has none."""
    from saengine.codes import context as code_context

    block = getattr(code_context.table("wind"), name, None)
    if block is None:
        raise ValueError(f"the code pack in force has no wind table '{name}'")
    return block


@dataclass
class RooftopItem:
    """A rooftop structure or piece of equipment: plan ``size`` (along X, along Y) and
    ``height`` [m], its cross-section and surface for Figure 6.2.21, how many."""

    name: str
    size: tuple[float, float]
    height: float
    section: str = "square"
    surface: str = "all"
    count: int = 1


def rooftop_equipment_wind(
    items: Iterable[RooftopItem],
    roof_height: float,
    widths: dict[str, float],
    qz_of: Any,
    gust: float,
) -> dict[str, Any]:
    """The wind force on rooftop structures and equipment of a building with mean roof height
    ``roof_height`` h (the default pack's Part 6 Sec 2.4.14-2.4.15): F = qz·G·Cf·Af (Eq 6.2.30) with qz
    at the centroid of Af (h + half the item's height, ``qz_of(z)`` [kN/m²]) and Cf of Figure
    6.2.21 (h/D of the item, D its least plan dimension), × the factor of Sec 2.4.15
    (:func:`saengine.fem.loads.rooftop_factor`, B = ``widths[case]``, the building's width
    across the wind). Returns ``{"WX": kN, "WY": kN, "items": [...]}``."""
    from saengine.fem.loads import rooftop_factor

    table = _wind_block("chimneys")
    out: dict[str, Any] = {"WX": 0.0, "WY": 0.0, "items": []}
    for item in items:
        lx, ly = item.size
        least = min(lx, ly)
        if least <= 0 or item.height <= 0:
            continue
        z = roof_height + item.height / 2
        qz = float(qz_of(z))
        row: dict[str, Any] = {"name": item.name, "count": item.count, "z_m": z, "qz_kPa": qz}
        for case, face in (("WX", ly), ("WY", lx)):
            area = face * item.height
            cf = chimney_cf(
                table, item.section, item.surface, item.height / least, least * math.sqrt(qz * 1e3)
            )
            factor = rooftop_factor(area, widths.get(case, 0.0), roof_height)
            force = qz * gust * cf * area * factor * item.count
            row[case] = {"Af_m2": area, "Cf": cf, "factor": factor, "F_kN": force}
            out[case] += force
        out["items"].append(row)
    return out


#
# A special structure that is clad (a shed of portal frames with roof and wall sheeting, a clad
# barrel vault or dome) is an enclosed or partially enclosed building, not an open framework:
# its wind is the main wind-force resisting system's pressures on the envelope (the default pack's Part 6
# Sec 2.4.11.2), applied on its panels (and not also as force coefficients on its members).
#
# - all heights (Eq 6.2.19): p = q·G·Cp − qi·(±GCpi), walls and roofs by Figure 6.2.6, arched
#   roofs by Figure 6.2.8, domes by Figure 6.2.7;
# - low-rise (Eq 6.2.20): p = qh·[(GCpf) − (±GCpi)], Figure 6.2.10, its basic load patterns
#   (four directions, each reference corner in turn) and the torsional ones;
# - windward roof overhangs: Cp 0.8 on their underside as well (Sec 2.4.10.4).
#
# The internal pressure is its own case (WI, + toward the internal surfaces) the combinations
# take with ± (Figure 6.2.5, note 3), and each direction is its own case (WX, WXN, WY, WYN: the
# pressures on a roof are not reversed by reversing the wind), with its variants (WX2 ...) where
# the figures give two values or cases (:func:`saengine.fem.loads.resolve_wind_cases`).

#: The wind directions of a clad structure's cases.
CLAD_DIRECTIONS = {
    "WX": np.array([1.0, 0.0, 0.0]),
    "WXN": np.array([-1.0, 0.0, 0.0]),
    "WY": np.array([0.0, 1.0, 0.0]),
    "WYN": np.array([0.0, -1.0, 0.0]),
}
_DIRECTION_NAMES = {"WX": "+X", "WXN": "-X", "WY": "+Y", "WYN": "-Y"}
#: A wall faces the wind where the cosine of its horizontal normal to the wind is below minus
#: this, away from it above this, a side wall between; a roof (or an arch) is normal to the wind
#: where the cosine of its ridge (axis) to the wind is below this.
FACING = 0.5
#: Roof slopes below this [°] count as flat when the roof's angle θ is averaged.
_LEVEL = 1.0
#: An arched roof whose springline is higher than this share of its span stands on an elevated
#: structure; lower, it springs from the ground (the arched roof table's two conditions).
ELEVATED_SPRINGLINE = 0.05


@dataclass
class CladPoint:
    """A piece of the envelope the wind presses on: ``key`` the caller's (a shell element),
    ``panel`` its panel, ``centroid`` [m] (z above the base), ``normal`` its outward unit
    normal, ``area`` [m²]."""

    key: Any
    panel: str
    centroid: np.ndarray
    normal: np.ndarray
    area: float

    @property
    def slope(self) -> float:
        """The angle of its plane from horizontal θ [°]."""
        return math.degrees(math.acos(min(1.0, max(-1.0, abs(float(self.normal[2]))))))


@dataclass
class CladWind:
    """The pressures of a clad structure's wind cases: ``pressures[case][key]`` [Pa], the net
    external pressure on each point (+ toward the surface); ``internal`` [Pa] the WI case's
    pressure toward the internal surfaces (0: no WI case) on the points ``inside``."""

    pressures: dict[str, dict[Any, float]] = field(default_factory=dict)
    internal: float = 0.0
    inside: set[Any] = field(default_factory=set)
    labels: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _horizontal(normal: np.ndarray) -> np.ndarray | None:
    h = np.array([normal[0], normal[1], 0.0])
    n = float(np.linalg.norm(h))
    return h / n if n > 1e-9 else None


def roof_axis(points: list[CladPoint]) -> np.ndarray | None:
    """The horizontal direction of a roof's ridge (or an arch's axis): normal to the
    direction its sloped parts mostly face (None: a flat roof)."""
    m = np.zeros((2, 2))
    for p in points:
        h = _horizontal(p.normal)
        if h is None:
            continue
        weight = p.area * float(np.linalg.norm(p.normal[:2]))
        m += weight * np.outer(h[:2], h[:2])
    if not m.any():
        return None
    values, vectors = np.linalg.eigh(m)
    facing = vectors[:, int(np.argmax(values))]
    return np.array([-facing[1], facing[0], 0.0])


def _overhangs(p: CladPoint, low: np.ndarray, high: np.ndarray, vertical: float) -> bool:
    """A roof point outside the walls' plan (by more than 1 mm)."""
    if p.slope > vertical:
        return False
    x, y = float(p.centroid[0]), float(p.centroid[1])
    return bool(x < low[0] - 1e-3 or x > high[0] + 1e-3 or y < low[1] - 1e-3 or y > high[1] + 1e-3)


def clad_structure_wind(
    points: list[CladPoint],
    *,
    eave: float,
    top: float,
    footprint: tuple[np.ndarray, np.ndarray],
    qz_of: Any,
    gust: float,
    gcpi: float,
    ri: float = 1.0,
    method: str = "allHeights",
    roof_form: str = "planar",
) -> CladWind:
    """The wind cases of a clad structure (see above): ``points`` its envelope, ``eave`` and
    ``top`` [m above the base] its eave (an arch's or dome's springline) and highest point,
    ``footprint`` the plan (low, high) corners of its walls (a roof beyond them overhangs),
    ``qz_of(z)`` the velocity pressure [Pa] at height z, ``gust`` G, ``gcpi``·``ri`` the
    internal pressure coefficient. ``method``: ``allHeights`` (Eq 6.2.19) or ``lowRise`` (Eq
    6.2.20, Figure 6.2.10, where the building is low-rise; otherwise all heights, with a note).
    ``roof_form``: ``planar`` (flat, gable, hip, monoslope: Figure 6.2.6), ``arched`` (Figure
    6.2.8) or ``dome`` (Figure 6.2.7)."""
    from saengine.fem import loads as fl

    out = CladWind()
    mwfrs = fl.mwfrs_table()
    if mwfrs is None or not points:
        out.notes.append("the code pack has no MWFRS wall and roof pressures")
        return out
    vertical = float(mwfrs.roof.verticalFrom)
    low, high = (np.asarray(c, dtype=float) for c in footprint)
    roofs = [p for p in points if p.slope <= vertical]
    sloped = [p for p in roofs if p.slope >= _LEVEL]
    theta = sum(p.slope * p.area for p in sloped) / sum(p.area for p in sloped) if sloped else 0.0
    h = fl.mean_roof_height(eave, top, theta)
    qh = float(qz_of(h))
    least = float(min(high[:2] - low[:2]))
    axis = roof_axis(sloped)
    out.summary = {
        "method": method,
        "roofForm": roof_form,
        "h_m": h,
        "eave_m": eave,
        "top_m": top,
        "theta_deg": theta,
        "qh_Pa": qh,
        "G": gust,
        "GCpi": gcpi,
        "Ri": ri,
        "cases": {},
    }
    low_rise_source = _cite(getattr(mwfrs, "lowRise", None))
    if method == "lowRise" and roof_form != "planar":
        out.notes.append(
            f"the low-rise pressures{low_rise_source} are for flat, gable and hip roofs: the "
            f"{roof_form} roof takes the pressures of all heights{_cite(mwfrs.roof)}"
        )
        method = "allHeights"
    elif method == "lowRise" and not (
        fl.is_low_rise(h, least) and fl.low_rise_gcpf(theta) is not None
    ):
        out.notes.append(
            f"not a low-rise building (h {h:.1f} m, least dimension {least:.1f} m"
            f"{low_rise_source}): the pressures of all heights{_cite(mwfrs.roof)} instead"
        )
        method = "allHeights"
    out.summary["method"] = method
    if method == "lowRise":
        _low_rise(out, points, low, high, eave, h, qh, theta, axis, least)
    else:
        _all_heights(out, points, low, high, eave, top, h, qh, axis, qz_of, gust, roof_form)
    if gcpi * ri:
        out.internal = gcpi * ri * qh
        out.inside = {p.key for p in points if not _overhangs(p, low, high, vertical)}
        out.labels[fl.WIND_INTERNAL_CASE] = (
            f"Wind internal pressure, (GCpi) {gcpi:g}"
            + (f" × Ri {ri:.3f}" if ri < 1 else "")
            + " × qh toward the internal surfaces"
        )
    out.summary["qi_Pa"] = out.internal
    return out


def _cite(table: Any) -> str:
    """`` (<the code pack's source of table>)``, empty when it has none."""
    source = getattr(table, "source", None) if table is not None else None
    return f" ({source})" if source else ""


def _record(out: CladWind, case: str, label: str, values: dict[Any, float], points: Any) -> None:
    out.pressures[case] = values
    out.labels[case] = label
    by_key = {p.key: p for p in points}
    force = np.zeros(3)
    for key, value in values.items():
        p = by_key[key]
        force += -value * p.area * p.normal
    out.summary["cases"][case] = {
        "label": label,
        "Fx_kN": round(float(force[0]) / 1e3, 3),
        "Fy_kN": round(float(force[1]) / 1e3, 3),
        "Fz_kN": round(float(force[2]) / 1e3, 3),
    }


def _is_arch(p: CladPoint, axis: np.ndarray | None) -> bool:
    """A point of an arched roof's surface: its normal across the arch's axis (not an end
    wall)."""
    return axis is None or abs(float(p.normal @ axis)) < FACING


def _extent(low: np.ndarray, high: np.ndarray, wind: np.ndarray) -> tuple[float, float, float]:
    """(windward edge coordinate, depth L along the wind, width B across it) of the plan."""
    across = np.array([-wind[1], wind[0]])
    corners = [low[:2], high[:2]]
    edge = min(float(c @ wind[:2]) for c in corners)
    size = (high - low)[:2]
    return edge, abs(float(size @ wind[:2])), abs(float(size @ across))


def _all_heights(
    out: CladWind,
    points: list[CladPoint],
    low: np.ndarray,
    high: np.ndarray,
    eave: float,
    top: float,
    h: float,
    qh: float,
    axis: np.ndarray | None,
    qz_of: Any,
    gust: float,
    roof_form: str,
) -> None:
    """Figure 6.2.6 walls and roofs (Figure 6.2.7 domes, 6.2.8 arched roofs), each direction."""
    from saengine.codes import context as code_context
    from saengine.fem import loads as fl

    mwfrs = fl.mwfrs_table()
    cp_windward = float(code_context.table("wind").cpWindward)
    flat = float(mwfrs.roof.flatAngle)
    vertical = float(mwfrs.roof.verticalFrom)
    upper = {p.key for p in points if p.centroid[2] >= eave - 1e-3}
    dome = None
    if roof_form == "dome":
        diameter = float(max(high[:2] - low[:2]))
        rise = top - eave
        cps = fl.dome_point_cps(rise / diameter, eave / diameter) if diameter > 0 else None
        if cps is None or rise <= 0:
            out.notes.append(
                f"dome f/D {rise / max(diameter, 1e-9):.3f} below the dome table's least (or "
                f"no dome table{_cite(getattr(mwfrs, 'domes', None))}): the roof table "
                f"instead{_cite(mwfrs.roof)}"
            )
        else:
            dome = ((low + high) / 2, diameter / 2, rise, cps)
            out.summary["dome"] = {
                "D_m": diameter,
                "f_m": rise,
                "hD_m": eave,
                "fOverD": rise / diameter,
                "hDOverD": eave / diameter,
                **{f"Cp{k}": v for k, v in cps.items()},
            }
    for direction, wind in CLAD_DIRECTIONS.items():
        windward_edge, depth, width = _extent(low, high, wind)
        if depth <= 0 or width <= 0:
            continue
        ratio = h / depth
        normal_to_ridge = axis is not None and abs(float(axis @ wind)) < FACING
        arched = None
        if roof_form == "arched" and normal_to_ridge:
            arch = [p for p in points if p.key in upper and _is_arch(p, axis)]
            span = depth if arch else 0.0  # springline to springline along the wind
            if span > 0:
                rise = (top - eave) / span
                elevated = eave > ELEVATED_SPRINGLINE * span
                cps = fl.arched_roof_cps(rise, elevated)
                note = (
                    f"arched roof r {rise:.2f} outside the arched roof table"
                    f"{_cite(getattr(mwfrs, 'arched', None))}: the roof table instead"
                )
                if cps is None and note not in out.notes:
                    out.notes.append(note)
                elif cps is not None:
                    arched = ({p.key for p in arch}, windward_edge, span, cps)
                    out.summary["arched"] = {"r": rise, "elevated": elevated, **cps}
        variants: list[dict[Any, float]] = [{}, {}]
        two = False
        for p in points:
            s = float(p.centroid[:2] @ wind[:2]) - windward_edge
            horizontal = _horizontal(p.normal)
            facing = float(horizontal @ wind) if horizontal is not None else 0.0
            q = qh
            if dome is not None and p.key in upper:
                centre, radius, rise, cps = dome
                offset = float((p.centroid[:2] - centre[:2]) @ wind[:2])
                sphere = (radius**2 + rise**2) / (2 * rise)
                spring = math.asin(min(1.0, radius / sphere))
                angle = math.asin(min(1.0, abs(offset) / sphere))
                position = 90.0 * (1 - angle / spring)  # note 6: 0 at the springline, 90 at top
                pair = (
                    fl.dome_cp(cps, position, offset < 0, "A"),
                    fl.dome_cp(cps, position, offset < 0, "B"),
                )
                q = float(qz_of(top))  # q at hD + f (Figure 6.2.7, note 2)
            elif arched is not None and p.key in arched[0]:
                _, start, span, cps = arched
                share = (float(p.centroid[:2] @ wind[:2]) - start) / span
                if share < 0.25:
                    pair = (cps["windward"][0], cps["windward"][-1])
                elif share > 0.75:
                    pair = (cps["leeward"], cps["leeward"])
                else:
                    pair = (cps["centre"], cps["centre"])
            elif p.slope > vertical:
                if facing < -FACING:
                    cp = cp_windward
                    q = float(qz_of(max(float(p.centroid[2]), 0.0)))
                elif facing > FACING:
                    cp = fl.leeward_coefficient(depth / width)
                else:
                    cp = float(mwfrs.sideWall)
                pair = (cp, cp)
            elif p.slope < flat or not normal_to_ridge or horizontal is None:
                pair = fl.roof_parallel_cp(max(s, 0.0), h, ratio, min(h / 2, depth) * width)
            elif facing < 0:
                pair = fl.roof_windward_cp(p.slope, ratio)
            else:
                cp = fl.roof_leeward_cp(p.slope, ratio)
                pair = (cp, cp)
            # Sec 2.4.10.4: the underside of a windward overhang, Cp 0.8 upward.
            under = float(mwfrs.overhang) if _overhangs(p, low, high, vertical) and s < 0 else 0.0
            for k in (0, 1):
                variants[k][p.key] = q * gust * pair[k] - qh * gust * under
            two = two or not math.isclose(pair[0], pair[1])
        name = _DIRECTION_NAMES[direction]
        kinds = ("Case A", "Case B") if dome is not None else ("first Cp", "second Cp")
        first = f"Wind {name}, {kinds[0]}" if two else f"Wind {name}"
        _record(out, fl.wind_variant_case(direction, 1), first, variants[0], points)
        if two:
            second = f"Wind {name}, {kinds[1]}"
            _record(out, fl.wind_variant_case(direction, 2), second, variants[1], points)


def _low_rise(
    out: CladWind,
    points: list[CladPoint],
    low: np.ndarray,
    high: np.ndarray,
    eave: float,
    h: float,
    qh: float,
    theta: float,
    axis: np.ndarray | None,
    least: float,
) -> None:
    """Figure 6.2.10: for each direction, each reference corner in turn (the end zones 2a wide
    on its side), and the torsional patterns unless exempt (note 5)."""
    from saengine.codes import context as code_context
    from saengine.fem import loads as fl

    mwfrs = fl.mwfrs_table()
    table = mwfrs.lowRise
    vertical = float(mwfrs.roof.verticalFrom)
    overhang = float(mwfrs.overhang)
    # a: note 9, the same rule as the components and cladding's edge zones.
    has_edges = getattr(code_context.table("wind"), "cladding", None) is not None
    a = fl.cladding_edge_width(least, h, True) if has_edges else 0.0
    end = table.endZoneFactor * a
    exempt = h <= table.exemptHeight
    out.summary.update({"a_m": a, "endZone_m": end, "torsionExempt": exempt})
    if not has_edges:
        out.notes.append("the code pack has no edge zone rule: no end zones (1E-4E)")
    if exempt:
        out.notes.append(
            "low-rise: no torsional load patterns (the exception for one storey with h ≤ "
            f"{table.exemptHeight:g} m{_cite(table)})"
        )
    for direction, wind in CLAD_DIRECTIONS.items():
        across = np.array([-wind[1], wind[0], 0.0])
        windward_edge, depth, width = _extent(low, high, wind)
        if depth <= 0 or width <= 0:
            continue
        transverse = axis is not None and abs(float(axis @ wind)) < FACING
        gcpf = fl.low_rise_gcpf(theta if transverse else 0.0) or {}  # note 7: θ = 0 along
        sides = sorted(float(c[:2] @ across[:2]) for c in (low, high))
        zone2_reach = min(table.zone2Fraction * depth, table.zone2EaveFactor * eave)
        patterns = [("reference corner on the low side", sides[0], False)]
        patterns.append(("reference corner on the high side", sides[1], False))
        if not exempt:
            patterns.append(("torsional, reference corner on the low side", sides[0], True))
            patterns.append(("torsional, reference corner on the high side", sides[1], True))
        name = _DIRECTION_NAMES[direction]
        for k, (label, reference, torsional) in enumerate(patterns, start=1):
            values: dict[Any, float] = {}
            for p in points:
                s = float(p.centroid[:2] @ wind[:2]) - windward_edge
                t = abs(float(p.centroid[:2] @ across[:2]) - reference)
                horizontal = _horizontal(p.normal)
                facing = float(horizontal @ wind) if horizontal is not None else 0.0
                if p.slope > vertical:
                    zone = "1" if facing < -FACING else "4" if facing > FACING else None
                    zone = zone or ("5" if t <= width / 2 else "6")
                elif transverse and horizontal is not None and p.slope >= _LEVEL:
                    zone = "2" if facing < 0 else "3"
                else:
                    zone = "2" if s < depth / 2 else "3"
                edge = zone in ("1", "2", "3", "4") and t <= end
                value = gcpf[zone + ("E" if edge else "")]
                if zone == "2" and value < 0 and s > zone2_reach:
                    value = gcpf["3E" if edge else "3"]  # note 8
                if torsional and zone in ("1", "2", "3", "4") and not edge and t > width / 2:
                    value *= table.torsionalShare  # note 5: zones 1T-4T
                under = overhang if _overhangs(p, low, high, vertical) and s < 0 else 0.0
                values[p.key] = qh * (value - under)
            case = fl.wind_variant_case(direction, k)
            _record(out, case, f"Wind {name}, low-rise, {label}", values, points)


# ──────────────── open buildings: net pressures on free roofs (MWFRS and C&C) ────────────────
#
# An open building (a canopy, a free-standing roof on columns: the wind settings' form ``clad``
# with the enclosure ``open``) takes net pressures on its roof, top and bottom surfaces together
# (the default pack's Part 6 Sec 2.4.12; the coefficients are the code pack's ``wind.openBuildings``):
#
#     p = qh · G · CN                                      (Eqs 6.2.27 MWFRS, 6.2.28 C&C)
#
# - qh at the mean roof height h, G the gust factor; CN positive toward the top surface;
# - wind normal to the ridge (γ = 0°, 180°): CNW on the windward half of the roof, CNL on the
#   leeward half, by roof form (monoslope, pitched, troughed), angle θ (linear between the rows;
#   below the pack's ``minAngle`` the monoslope's first row) and blockage (clear: at most 50 %
#   of the space under the roof blocked; obstructed: more); a monoslope's γ = 0° blows down its
#   slope, 180° up it;
# - wind along the ridge (γ = 90°), and normal to a nearly flat monoslope with small h/L: CN by
#   the distance from the windward edge in multiples of h;
# - every load case of the figures (A, B) is its own variant of each direction (WX, WX2, ...).
#
# The form is read from the panels: one slope direction is a monoslope; two, a pitched roof
# where the slopes face away from the ridge line and a troughed one where they face toward it.


def open_buildings_table() -> Any:
    """The code pack's free roof table, None without one."""
    from saengine.codes import context as code_context

    return getattr(code_context.table("wind"), "openBuildings", None)


def _lerp(x: float, xs: list[float], ys: list[float]) -> float:
    from saengine.fem.loads import _interpolate

    return float(_interpolate(x, xs, ys))


def free_roof_cases(form: str) -> list[str]:
    """The load cases (A, B) of a free roof form's figure, in order."""
    table = open_buildings_table()
    rows = getattr(table.mwfrs, form) if table is not None else []
    return sorted({r.case for r in rows})


def free_roof_cn(
    form: str, theta: float, case: str, blockage: str = "clear", reverse: bool = False
) -> tuple[float, float] | None:
    """(CNW, CNL) of a free roof with the wind normal to its ridge (Figures 6.2.18(a)-(c)):
    ``form`` monoslope, pitched or troughed, angle θ [°] (linear between the rows; below the
    pack's ``minAngle`` the monoslope's first row, note 3), load ``case`` A or B, ``blockage``
    clear or obstructed; ``reverse`` the monoslope's γ = 180° (the wind up the slope). None above
    the pack's ``maxAngle`` or without the table."""
    table = open_buildings_table()
    if table is None or theta > table.maxAngle:
        return None
    rows = getattr(table.mwfrs, form)
    if theta < table.minAngle:
        rows = table.mwfrs.monoslope
        theta = min(float(r.angle) for r in rows)
    rows = sorted((r for r in rows if r.case == case), key=lambda r: r.angle)
    if not rows:
        return None

    def pair(r: Any) -> tuple[float, float]:
        if reverse and r.clearReverse is not None:
            return r.clearReverse if blockage == "clear" else r.obstructedReverse
        return r.clear if blockage == "clear" else r.obstructed

    angles = [float(r.angle) for r in rows]
    return (
        _lerp(theta, angles, [pair(r)[0] for r in rows]),
        _lerp(theta, angles, [pair(r)[1] for r in rows]),
    )


def free_roof_along_cn(distance: float, case: str, blockage: str = "clear") -> float | None:
    """CN of a free roof point ``distance`` from the windward edge, in multiples of h, with the
    wind along the ridge (Figure 6.2.18(d)); None without the table."""
    table = open_buildings_table()
    if table is None:
        return None
    zones = table.mwfrs.along.zones
    zone = next((z for z in zones if z.upTo is None or distance <= z.upTo), zones[-1])
    return float(zone.cases[case][blockage])


def free_roof_cladding(
    form: str, theta: float, blockage: str, area: float | None, a: float
) -> list[dict[str, Any]] | None:
    """CN of the components and cladding of a free roof by zone (Figures 6.2.19(a)-(c)): for
    the effective wind area ``area`` [m²] (None: the smallest band) against a² of the edge
    distance ``a`` [m], linear between the roof angles. ``[{"zone", "label", "CNPos",
    "CNNeg"}]``; None above the pack's ``maxAngle`` or without the table."""
    table = open_buildings_table()
    cladding = getattr(table, "cladding", None) if table is not None else None
    if cladding is None or theta > table.maxAngle:
        return None
    rows = sorted(getattr(cladding, form), key=lambda r: r.angle)
    bands = [float(b) for b in cladding.areaBands]
    ratio = 0.0 if area is None or a <= 0 else area / (a * a)
    band = next((k for k, b in enumerate(bands) if ratio <= b), len(bands))
    angles = [float(r.angle) for r in rows]

    def flow(r: Any) -> dict[str, list[tuple[float, float]]]:
        return r.clear if blockage == "clear" else r.obstructed

    labels = dict(cladding.zoneLabels)
    ridge = form != "monoslope" and theta >= cladding.ridgeEdgeFrom
    out = []
    for zone in sorted(flow(rows[0]), reverse=True):
        values = [flow(r)[zone][min(band, len(flow(r)[zone]) - 1)] for r in rows]
        label = labels.get(zone, f"zone {zone}")
        if ridge:
            label += " (each slope's edges, the ridge or valley included)"
        out.append(
            {
                "zone": zone,
                "label": label,
                "CNPos": _lerp(theta, angles, [v[0] for v in values]),
                "CNNeg": _lerp(theta, angles, [v[1] for v in values]),
            }
        )
    return out


def free_roof_form(points: list[CladPoint], axis: np.ndarray | None, centre: np.ndarray) -> str:
    """monoslope, pitched or troughed: the form of a free roof from its sloped points."""
    if axis is None:
        return "monoslope"
    across = np.array([-axis[1], axis[0]])
    sides = [0.0, 0.0]
    away = toward = 0.0
    for p in points:
        h = _horizontal(p.normal)
        if h is None or p.slope < _LEVEL:
            continue
        weight = p.area * float(np.linalg.norm(p.normal[:2]))
        facing = float(h[:2] @ across)
        sides[0 if facing > 0 else 1] += weight
        offset = float((p.centroid[:2] - centre[:2]) @ across)
        if facing * offset > 0:
            away += weight
        else:
            toward += weight
    if min(sides) < 0.1 * sum(sides):
        return "monoslope"
    return "pitched" if away >= toward else "troughed"


def free_roof_wind(
    points: list[CladPoint],
    *,
    eave: float,
    top: float,
    plan: tuple[np.ndarray, np.ndarray],
    qz_of: Any,
    gust: float,
    blockage: str = "clear",
    area: float | None = None,
) -> CladWind:
    """The wind cases of an open building's free roof (see above): ``points`` its roof,
    ``eave`` and ``top`` [m above the base] its lowest and highest points, ``plan`` the (low,
    high) corners of the roof's plan, ``qz_of(z)`` the velocity pressure [Pa] at height z,
    ``gust`` G, ``blockage`` clear or obstructed, ``area`` the components' effective wind area
    [m²] (None: the smallest band) for the reported C&C values. No internal pressure. Empty
    (with a note) above the pack's roof angle or without its table."""
    from saengine.codes import context as code_context
    from saengine.fem import loads as fl

    out = CladWind()
    table = open_buildings_table()
    if table is None or not points:
        out.notes.append("the code pack has no net pressure coefficients of free roofs")
        return out
    mwfrs = fl.mwfrs_table()
    vertical = float(mwfrs.roof.verticalFrom) if mwfrs is not None else 80.0
    roofs = [p for p in points if p.slope <= vertical]
    if len(roofs) < len(points):
        out.notes.append(
            f"{len(points) - len(roofs)} wall or fascia panel(s) of the open building take no "
            "free roof pressures (fascia panels as inverted parapets are not covered here)"
        )
    if not roofs:
        out.notes.append("the open building has no roof panels")
        return out
    sloped = [p for p in roofs if p.slope >= _LEVEL]
    theta = sum(p.slope * p.area for p in sloped) / sum(p.area for p in sloped) if sloped else 0.0
    if theta > table.maxAngle:
        out.notes.append(
            f"free roof θ {theta:.1f}° above the figures' {table.maxAngle:g}°{_cite(table)}"
        )
        return out
    low, high = (np.asarray(c, dtype=float) for c in plan)
    axis = roof_axis(sloped)
    form = free_roof_form(roofs, axis, (low + high) / 2)
    h = fl.mean_roof_height(eave, top, theta)
    qh = float(qz_of(h))
    blockage = "obstructed" if blockage == "obstructed" else "clear"
    out.summary = {
        "method": "openBuilding",
        "roofForm": form,
        "blockage": blockage,
        "h_m": h,
        "eave_m": eave,
        "top_m": top,
        "theta_deg": theta,
        "qh_Pa": qh,
        "G": gust,
        "GCpi": 0.0,
        "Ri": 1.0,
        "cases": {},
    }
    # A monoslope's γ = 0°: the wind blowing down the slope (the way its normal leans).
    lean = np.zeros(2)
    for p in sloped:
        lean += p.area * p.normal[:2]
    along = table.mwfrs.along
    lo, hi = table.hOverL
    cases = free_roof_cases(form) or ["A"]
    for direction, wind in CLAD_DIRECTIONS.items():
        edge, depth, width = _extent(low, high, wind)
        if depth <= 0 or width <= 0:
            continue
        ratio = h / depth
        normal = axis is None or abs(float(axis @ wind)) < FACING
        flat = form == "monoslope" and theta < along.flatMonoslopeAngle
        small = along.flatMonoslopeRatio[0] <= ratio < along.flatMonoslopeRatio[1]
        use_along = not normal or (flat and small)
        name = _DIRECTION_NAMES[direction]
        if not lo <= ratio <= hi and not (flat and small):
            out.notes.append(
                f"{name}: h/L {ratio:.2f} outside the figures' {lo:g}-{hi:g}; the coefficients "
                "are used as printed"
            )
        reverse = form == "monoslope" and float(lean @ wind[:2]) < 0
        for k, case in enumerate(cases, start=1):
            values: dict[Any, float] = {}
            pair = None if use_along else free_roof_cn(form, theta, case, blockage, reverse)
            for p in roofs:
                s = float(p.centroid[:2] @ wind[:2]) - edge
                if pair is None:
                    distance = max(s, 0.0) / h if h > 0 else math.inf
                    cn = free_roof_along_cn(distance, case, blockage) or 0.0
                else:
                    cn = pair[0] if s < depth / 2 else pair[1]
                values[p.key] = qh * gust * cn
            if not normal:
                how = "wind along the ridge"
            elif use_along:
                how = "by distance from the windward edge"
            else:
                how = f"γ {180 if reverse else 0}°"
            label = f"Wind {name}, free {form} roof Case {case} ({blockage} flow, {how})"
            _record(out, fl.wind_variant_case(direction, k), label, values, roofs)
    # The components and cladding (reported): p = qh·G·CN by zone.
    least = float(min(high[:2] - low[:2]))
    has_edges = getattr(code_context.table("wind"), "cladding", None) is not None
    a = fl.cladding_edge_width(least, h, True) if has_edges else 0.0
    zones = free_roof_cladding(form, theta, blockage, area, a)
    if zones:
        for z in zones:
            z["pPos_kPa"] = qh * gust * z["CNPos"] / 1e3
            z["pNeg_kPa"] = qh * gust * z["CNNeg"] / 1e3
        out.summary["cladding"] = {"a_m": a, "area_m2": area, "zones": zones}
    return out

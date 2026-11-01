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

A clad special structure (a shed with its sheeting, a clad vault or dome: the wind settings'
form ``clad``) is a building instead: :func:`clad_structure_wind` below gives the pressures on
its panels (walls and roofs with internal pressure, BNBC 2020 Part 6 Sec 2.4.11.2).

Not covered here: the net pressures on free roofs of open buildings (the canopy's cladding),
shielding of one frame by another (every member is loaded fully: conservative for a row of
frames), and vortex shedding.
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


# ───────────────────── clad structures: pressures on the panels (MWFRS) ─────────────────────
#
# A special structure that is clad (a shed of portal frames with roof and wall sheeting, a clad
# barrel vault or dome) is an enclosed or partially enclosed building, not an open framework:
# its wind is the main wind-force resisting system's pressures on the envelope (BNBC 2020 Part 6
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

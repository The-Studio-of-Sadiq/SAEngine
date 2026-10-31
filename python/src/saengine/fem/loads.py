"""Loads of the analysis model from the project settings (BNBC 2020 Part 6 Chapter 2).

Pure functions: given the building's levels, weights and plan, they return the equivalent
static seismic and wind forces per level and the beam loads of slab areas. The derivation of the
analysis model (:mod:`saengine.fem.derive`) applies them; every formula names its clause, and
the code pack in force (:func:`saengine.codes.context.current`, BNBC 2020 by default) holds
the coefficients.

Units: m, kN, s.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from saengine.codes import context as code_context
from saengine.fem.slab_load_shapes import EdgeProfile, slab_load_shapes

# ───────────────────────── seismic: equivalent static force method ─────────────────────────


def approximate_period(height: float, system: str) -> float:
    """Fundamental period T = Ct·hn^m [s] for a building ``height`` metres tall."""
    seismic = code_context.table("seismic")
    row = seismic.systems.get(system)
    family = (row.periodFamily if row else None) or "other"
    coefficient = seismic.periodCoefficients[family]
    ct, m = coefficient.Ct, coefficient.m
    return ct * height**m


def normalized_spectrum(period: float, site_class: str) -> float:
    """Normalized acceleration response spectrum Cs(T) for the site class (5 % damping)."""
    seismic = code_context.table("seismic")
    site = seismic.siteClasses[site_class]
    s, tb, tc, td = site.S, site.TB, site.TC, site.TD
    eta = seismic.dampingEta
    if period <= tb:
        return s * (1 + period / tb * (2.5 * eta - 1))
    if period <= tc:
        return 2.5 * s * eta
    if period <= td:
        return 2.5 * s * eta * tc / period
    return 2.5 * s * eta * tc * td / period**2


def design_acceleration(
    period: float, site_class: str, z: float, importance: float, r: float
) -> float:
    """Design spectral acceleration Sa = (2/3)·(Z·I/R)·Cs, as a fraction of g."""
    return 2 / 3 * z * importance / r * normalized_spectrum(period, site_class)


def vertical_distribution(
    levels: list[tuple[float, float]], base_shear: float, period: float
) -> list[float]:
    """Lateral force at each level: Fx = V·wx·hx^k / Σ wi·hi^k for (height, weight) levels.

    k = 1 for T ≤ 0.5 s, 2 for T ≥ 2.5 s, linear in between.
    """
    k = 1.0 if period <= 0.5 else 2.0 if period >= 2.5 else 1 + (period - 0.5) / 2
    weights = [w * h**k for h, w in levels]
    total = sum(weights)
    return [base_shear * w / total if total else 0.0 for w in weights]


# ───────────────────────── wind: main wind-force resisting system ─────────────────────────

#: The project's overrides of Kd, Kzt and G (Project Settings > Wind), while its loads are made.
_WIND_OVERRIDES: ContextVar[dict[str, float] | None] = ContextVar("wind_overrides", default=None)


@contextmanager
def wind_overrides(wind: Any) -> Iterator[None]:
    """Kd, Kzt and G of the settings' ``wind`` (``directionality``, ``topographic``, ``gust``)
    instead of the code pack's, where given, for the wind loads made inside."""
    values = {
        k: float(v)
        for k in ("directionality", "topographic", "gust")
        if (v := getattr(wind, k, None)) is not None
    }
    token = _WIND_OVERRIDES.set(values)
    try:
        yield
    finally:
        _WIND_OVERRIDES.reset(token)


def wind_factor(name: str) -> float:
    """Kd ("directionality"), Kzt ("topographic") or G ("gust"): the project's override, else
    the code pack's (BNBC 2020 Table 6.2.12, Sec 2.4.7, Sec 2.4.8.1)."""
    own = (_WIND_OVERRIDES.get() or {}).get(name)
    return own if own is not None else float(getattr(code_context.table("wind"), name))


def exposure_coefficient(height: float, exposure: str) -> float:
    """Velocity pressure exposure coefficient Kz at ``height`` metres (Table 6.2.11)."""
    profile = code_context.table("wind").exposures[exposure]
    alpha, zg = profile.alpha, profile.zg
    return 2.01 * (max(height, 4.57) / zg) ** (2 / alpha)


def velocity_pressure(height: float, speed: float, exposure: str, importance: float) -> float:
    """qz = 0.000613·Kz·Kzt·Kd·V²·I [kN/m²], V in m/s."""
    return (
        0.000613
        * exposure_coefficient(height, exposure)
        * wind_factor("topographic")
        * wind_factor("directionality")
        * speed**2
        * importance
    )


def leeward_coefficient(aspect: float) -> float:
    """Leeward wall Cp for a plan aspect L/B (depth along the wind over width across it)."""
    points = code_context.table("wind").cpLeeward
    if aspect <= points[0][0]:
        return points[0][1]
    for (a0, c0), (a1, c1) in pairwise(points):
        if aspect <= a1:
            return c0 + (c1 - c0) * (aspect - a0) / (a1 - a0)
    return points[-1][1]


def wind_level_forces(
    heights: list[float], width: float, depth: float, speed: float, exposure: str, importance: float
) -> list[float]:
    """Wind force at each level [kN] for wind across a building ``width`` wide and ``depth`` deep
    at every storey (a prismatic building; :func:`wind_levels` takes each storey's own extent).

    Windward pressure qz·G·Cp varies with height; leeward suction qh·G·Cp uses the roof height.
    Each level takes the wall area from halfway down to the level below to halfway up to the one
    above (the roof level the half below it).
    """
    n = len(heights)
    return [
        level.force
        for level in wind_levels(
            heights, [(0.0, width)] * n, [depth] * n, speed, exposure, importance
        )
    ]


@dataclass(frozen=True)
class WindLevel:
    """The wind load a level takes (BNBC 2020 Part 6 Sec 2.4.11.2): ``force`` [kN] along the
    wind; ``centre`` [m], the position across the wind of its resultant, the geometric centre of
    the face it takes (Sec 2.4.11.3, p. 559: the eccentricity is "measured from the geometric
    center of the building face"); ``width`` [m], that face's mean width B across the wind;
    ``torsion_width`` [m], the force-weighted width Σ(F_i·B_i)/F of its part-faces, so that the
    torsion of Figure 6.2.9 (p. 574), e = 0.15·B on each part-face, sums to F·0.15·torsion_width
    (at a setback level larger than F·0.15·width); None means ``width`` (one face)."""

    force: float
    centre: float
    width: float
    torsion_width: float | None = None

    @property
    def torsion_arm(self) -> float:
        """The width B the torsional eccentricity e = k·B is taken of [m]."""
        return self.width if self.torsion_width is None else self.torsion_width


def wind_levels(
    heights: list[float],
    spans: list[tuple[float, float]],
    depths: list[float],
    speed: float,
    exposure: str,
    importance: float,
) -> list[WindLevel]:
    """The wind load of each level of a building whose storeys differ in plan (setbacks,
    podiums): storey ``i`` (from level ``i - 1``, or the base, up to level ``i``) has the face
    ``spans[i]`` = (low, high) across the wind [m] and the depth ``depths[i]`` along it.

    Level ``i`` takes the lower half of storey ``i`` with that storey's face and the upper half
    of storey ``i + 1`` with that one's (the roof the half below it). Windward pressure
    qz·G·Cp at the level's height; leeward suction qh·G·Cp(L/B) at the roof height h with each
    storey's own L/B (Figure 6.2.6). The resultant acts at the area- and pressure-weighted
    centre of the two half-faces.
    """
    n = len(heights)
    if not n:
        return []
    if len(spans) != n or len(depths) != n:
        raise ValueError("wind_levels: one span and one depth per level")
    wind = code_context.table("wind")
    qh = velocity_pressure(heights[-1], speed, exposure, importance)

    def leeward(i: int) -> float:
        width = spans[i][1] - spans[i][0]
        if width <= 0:
            return 0.0
        return qh * wind_factor("gust") * leeward_coefficient(depths[i] / width)

    out = []
    for i, z in enumerate(heights):
        windward = (
            velocity_pressure(z, speed, exposure, importance)
            * wind_factor("gust")
            * wind.cpWindward
        )
        parts = [(i, (z - (heights[i - 1] if i else 0.0)) / 2)]
        if i + 1 < n:
            parts.append((i + 1, (heights[i + 1] - z) / 2))
        force = moment = area = twist = 0.0
        for storey, tributary in parts:
            low, high = spans[storey]
            width = max(high - low, 0.0)
            f = (windward - leeward(storey)) * width * tributary
            force += f
            moment += f * (low + high) / 2
            twist += f * width
            area += width * tributary
        tributary_height = sum(t for _, t in parts)
        width = area / tributary_height if tributary_height else 0.0
        if force:
            centre = moment / force
        else:
            low, high = spans[i]
            centre = (low + high) / 2
        out.append(WindLevel(force, centre, width, twist / force if force else width))
    return out


def wind_torsion_moments(levels: list[WindLevel], eccentricity: float) -> list[float]:
    """The torsional moment at each level [kN·m] of the wind ``levels`` displaced by
    ``eccentricity``·B across the wind (BNBC 2020 Part 6 Figure 6.2.9, p. 574: Case 2,
    M_T = 0.75·(P_WX + P_LX)·B_X·e_X with e_X = ±0.15·B_X; here unfactored, F·e with
    F = (P_W + P_L)·B per unit height, the 0.75 or 0.563 going in the combinations, see
    :func:`wind_design_variants`). Positive counter-clockwise about Z (the sign is ±).

    At a setback level each part-face takes its own e = 0.15·B_i, so the moment is
    Σ F_i·0.15·B_i = F·0.15·:attr:`WindLevel.torsion_arm`, not F·0.15 times the mean width."""
    return [level.force * eccentricity * level.torsion_arm for level in levels]


#: The torsional wind case of each wind case: its moments alone (no force), from
#: :func:`wind_torsion_moments`.
WIND_TORSION_CASES = {"WX": "WTX", "WY": "WTY"}


@dataclass(frozen=True)
class WindDesignCases:
    """The factors of the design wind load cases (BNBC 2020 Part 6 Sec 2.4.11.3 and Figure
    6.2.9, pp. 559 and 574-575), from the code pack's wind table (``designCases``).

    ``partial``: Case 2, the share of the pressure with the torsion (0.75); ``eccentricity``:
    e / B (0.15); ``simultaneous``: Case 3, the share of each direction acting together
    (0.75); ``simultaneousTorsional``: Case 4, the share of each direction with both torsions
    (0.563); ``exemptHeight``: the exception's one-storey height limit h [m] (9.1) under which,
    and for two storeys or less with flexible diaphragms, only Cases 1 and 3 apply."""

    partial: float
    eccentricity: float
    simultaneous: float
    simultaneousTorsional: float
    exemptHeight: float


def wind_design_cases() -> WindDesignCases | None:
    """The design wind load cases of the code pack in force; None when its wind table has none
    (only Case 1 then: the caller reports it)."""
    table = getattr(code_context.table("wind"), "designCases", None)
    if table is None:
        return None

    def value(name: str) -> float:
        return float(table[name] if isinstance(table, dict) else getattr(table, name))

    return WindDesignCases(
        partial=value("partial"),
        eccentricity=value("eccentricity"),
        simultaneous=value("simultaneous"),
        simultaneousTorsional=value("simultaneousTorsional"),
        exemptHeight=value("exemptHeight"),
    )


def wind_torsion_exempt(
    storeys: int, height: float, rigid_diaphragms: bool, cases: WindDesignCases
) -> bool:
    """Whether a building needs only Cases 1 and 3 (Sec 2.4.11.3, Exception, p. 559): one
    storey with h ≤ 9.1 m, or two storeys or less designed with flexible diaphragms (light-frame
    construction, the third exempt kind, is not one SAEngine models). ``rigid_diaphragms`` is
    False only for floors designed as flexible diaphragms, not for RC slabs analysed with their
    modelled in-plane stiffness (SAEngine's derive passes True)."""
    if storeys <= 1 and height <= cases.exemptHeight:
        return True
    return storeys <= 2 and not rigid_diaphragms


def _sign(value: float) -> str:
    return "+" if value > 0 else "-"


def wind_design_variants(
    factors: dict[str, float], cases: WindDesignCases, torsion: bool = True
) -> list[tuple[str, dict[str, float]]]:
    """The design wind load cases of a combination (Figure 6.2.9) as ``(label, {case:
    factor})`` on WX, WY, WTX and WTY, from its wind factors ``factors`` (``{"WX": f}`` or
    ``{"WY": f}``, the sign the wind's direction). A combination with both WX and WY (made by
    hand) or neither is returned unchanged. Without ``torsion`` (an exempt building,
    :func:`wind_torsion_exempt`, or a model without WTX and WTY) only Cases 1 and 3.

    - Case 1: the combination itself;
    - Case 2: 0.75 of it with ±0.75 of its torsion (e = ±0.15·B);
    - Case 3: 0.75 of it with ±0.75 of the other direction;
    - Case 4: 0.563 of it with ±0.563 of the other direction and ±0.563 of both torsions.

    The other direction and each torsion take the factor's magnitude with both signs ("plus or
    minus, whichever causes the more severe load effect", Sec 2.4.11.3).
    """
    wx, wy = factors.get("WX", 0.0), factors.get("WY", 0.0)
    if bool(wx) == bool(wy):
        return [("", {k: v for k, v in factors.items() if v})]
    own, other = ("WX", "WY") if wx else ("WY", "WX")
    f = wx or wy
    pm = (1.0, -1.0)
    out: list[tuple[str, dict[str, float]]] = [("Case 1", {own: f})]
    if torsion:
        p = cases.partial * f
        for s in pm:
            out.append((f"Case 2 {_sign(s)}e", {own: p, WIND_TORSION_CASES[own]: s * abs(p)}))
    q = cases.simultaneous * f
    for s in pm:
        out.append((f"Case 3 {_sign(s)}{other}", {own: q, other: s * abs(q)}))
    if torsion:
        r = cases.simultaneousTorsional * f
        for s in pm:
            for t1 in pm:
                for t2 in pm:
                    out.append(
                        (
                            f"Case 4 {_sign(s)}{other} {_sign(t1)}e{own[1]} {_sign(t2)}e{other[1]}",
                            {
                                own: r,
                                other: s * abs(r),
                                WIND_TORSION_CASES[own]: t1 * abs(r),
                                WIND_TORSION_CASES[other]: t2 * abs(r),
                            },
                        )
                    )
    return out


# ───────────────────────── slab areas to beams ─────────────────────────


# ─────────────── wind: gust-effect factor of flexible buildings (Sec 2.4.8.2) ───────────────


def _resonance_term(eta: float) -> float:
    """R_ℓ = 1/η − (1 − e^(−2η))/(2η²), 1 at η = 0 (BNBC 2020 Part 6 Sec 2.4.8.2, Eq. 6.2.15;
    ASCE 7-05 Eq. 6-13)."""
    if eta <= 0:
        return 1.0
    return 1 / eta - (1 - math.exp(-2 * eta)) / (2 * eta * eta)


def flexible_gust_factor(
    height: float,
    width: float,
    depth: float,
    frequency: float,
    speed: float,
    exposure: str,
    damping: float | None = None,
) -> dict[str, float] | None:
    """The gust-effect factor Gf of a flexible or dynamically sensitive building (BNBC 2020
    Part 6 Sec 2.4.8.2, Eq. 6.2.8-6.2.16; ASCE 7-05 Sec 6.5.8.2) of mean roof height ``height``,
    ``width`` B across the wind and ``depth`` L along it [m], natural frequency n1
    ``frequency`` [Hz] in the wind's direction and basic wind speed V ``speed`` [m/s]:

        Gf = 0.925 · (1 + 1.7·Iz̄·√(gQ²Q² + gR²R²)) / (1 + 1.7·gv·Iz̄)

    with z̄ = 0.6h ≥ z_min, Iz̄ = c·(10/z̄)^(1/6), Lz̄ = ℓ·(z̄/10)^ε̄, Q² = 1/(1 + 0.63·((B +
    h)/Lz̄)^0.63), Vz̄ = b̄·(z̄/10)^ᾱ·V, N1 = n1·Lz̄/Vz̄, Rn = 7.47·N1/(1 + 10.3·N1)^(5/3),
    R² = Rn·Rh·RB·(0.53 + 0.47·RL)/β, gR = √(2 ln 3600n1) + 0.577/√(2 ln 3600n1) and the
    R_ℓ of η = 4.6n1h/Vz̄, 4.6n1B/Vz̄, 15.4n1L/Vz̄. ``damping`` β (ratio of critical): the code
    pack's when None. Returns Gf and its terms; None when the code pack has no flexible-gust
    table or no terrain constants for ``exposure``."""
    wind = code_context.table("wind")
    table = getattr(wind, "flexible", None)
    terrain = wind.exposures[exposure]
    if table is None or any(
        getattr(terrain, k, None) is None for k in ("c", "l", "epsilonBar", "alphaBar", "bBar")
    ):
        return None
    beta = damping if damping is not None else table.damping
    z = max(table.heightFactor * height, terrain.zmin or 0.0)
    intensity = terrain.c * (10 / z) ** (1 / 6)
    scale = terrain.l * (z / 10) ** terrain.epsilonBar
    q2 = 1 / (1 + 0.63 * ((width + height) / scale) ** 0.63)
    mean_speed = terrain.bBar * (z / 10) ** terrain.alphaBar * speed
    reduced = frequency * scale / mean_speed
    rn = 7.47 * reduced / (1 + 10.3 * reduced) ** (5 / 3)
    rh = _resonance_term(4.6 * frequency * height / mean_speed)
    rb = _resonance_term(4.6 * frequency * width / mean_speed)
    rl = _resonance_term(15.4 * frequency * depth / mean_speed)
    r2 = rn * rh * rb * (0.53 + 0.47 * rl) / beta
    log = math.sqrt(2 * math.log(3600 * frequency))
    g_r = log + 0.577 / log
    gf = (
        table.lead
        * (1 + 1.7 * intensity * math.sqrt(table.gQ**2 * q2 + g_r**2 * r2))
        / (1 + 1.7 * table.gv * intensity)
    )
    return {
        "Gf": gf,
        "n1_Hz": frequency,
        "beta": beta,
        "zbar_m": z,
        "Iz": intensity,
        "Lz_m": scale,
        "Q": math.sqrt(q2),
        "Vz_ms": mean_speed,
        "R": math.sqrt(r2),
        "gR": g_r,
    }


def is_flexible(frequency: float) -> bool:
    """Whether a building of natural frequency n1 ``frequency`` [Hz] is flexible, "a
    fundamental natural frequency less than 1 Hz" (BNBC 2020 Part 6 Sec 2.4.2, definitions)."""
    table = getattr(code_context.table("wind"), "flexible", None)
    return table is not None and frequency < table.frequencyLimit


# ───────────────────── wind: components and cladding (Sec 2.4.11.5) ─────────────────────


def cladding_coefficient(curve: Any, area: float | None) -> float:
    """(GCp) of a components-and-cladding ``curve`` (:class:`saengine.codes.tables.
    CladdingCurve`) for the effective wind area ``area`` [m²], linear in log A between its two
    areas; None: the smallest area's (the largest magnitude, a safe default)."""
    if area is None or area <= curve.area1:
        return float(curve.gcp1)
    if area >= curve.area2:
        return float(curve.gcp2)
    t = math.log10(area / curve.area1) / math.log10(curve.area2 / curve.area1)
    return float(curve.gcp1 + (curve.gcp2 - curve.gcp1) * t)


def cladding_edge_width(least: float, height: float, low_rise: bool) -> float:
    """The width a [m] of the edge and corner zones (BNBC 2020 Part 6 Sec 2.4.11.5 figures;
    ASCE 7-05 Figures 6-11 and 6-17, notes): 10 % of the least horizontal dimension ``least``,
    and for a low-rise building not over 0.4h, but not less than 4 % of the least dimension
    (low-rise) nor 0.9 m."""
    table = code_context.table("wind").cladding
    a = table.edgeFraction * least
    if low_rise:
        a = min(a, table.edgeHeightFraction * height)
        return max(a, table.edgeMinFraction * least, table.edgeMin)
    return max(a, table.edgeMin)


#: What each zone of the components-and-cladding figures is.
CLADDING_ZONES = {
    ("wall", "4"): "wall, interior",
    ("wall", "5"): "wall, corner (within a of a corner)",
    ("roof", "1"): "roof, interior",
    ("roof", "2"): "roof, edge (within a of an edge)",
    ("roof", "3"): "roof, corner (within a of two edges)",
}


def cladding_pressures(
    height: float,
    least: float,
    speed: float,
    exposure: str,
    importance: float,
    *,
    area: float | None = None,
    enclosure: str = "enclosed",
    parapet: float | None = None,
) -> dict[str, Any] | None:
    """The design pressures of components and cladding by zone (BNBC 2020 Part 6 Sec 2.4.11.5;
    ASCE 7-05 Sec 6.5.12.4) of a flat-roofed building (θ ≤ 10°) of mean roof height ``height``
    and least horizontal dimension ``least`` [m], for an effective wind area ``area`` [m²]
    (None: the smallest tabulated, the largest pressures) and the internal pressure of its
    ``enclosure``:

        p = qh·[(GCp) − (±GCpi)]  [kN/m²]

    (h ≤ 18.3 m, Eq. 6.2.22; above it Eq. 6.2.23, q = qh on the leeward and side walls and
    the roof, qz on the windward wall, which is qh at the top: the pressures given are those
    at h, the largest). Positive towards the surface. A parapet ``parapet`` m high, at least the
    code pack's 0.9 m, turns roof zone 3 into zone 2 (figure notes); the parapet's own net
    pressures, at qp of its top, are Case A (windward: wall zone 5 positive on the front, roof
    zone 3 suction on the back) and Case B (leeward: wall positive on the back, wall zone 5
    suction on the front) (ASCE 7-05 Sec 6.5.12.4.4, a solid parapet, GCpi = 0). Returns
    ``{"h_m", "qh_kPa", "lowRise", "a_m", "area_m2", "enclosure", "GCpi", "zones": [{"surface",
    "zone", "label", "GCpPos", "GCpNeg", "pPos_kPa", "pNeg_kPa"}], "parapet"}``; None when the
    code pack has no cladding table."""
    table = getattr(code_context.table("wind"), "cladding", None)
    if table is None:
        return None
    low = height <= table.lowRiseHeight
    curves = table.lowRise if low else table.highRise
    gcpi = float(table.internal.get(enclosure, table.internal.get("enclosed", 0.18)))
    qh = velocity_pressure(height, speed, exposure, importance)
    walls = table.lowRiseWallFactor if low else 1.0
    corner_as_edge = parapet is not None and parapet >= table.parapetCorner

    def curve_value(surface: str, zone: str, sign: str) -> float | None:
        for curve in curves:
            if (curve.surface, curve.zone, curve.sign) == (surface, zone, sign):
                value = cladding_coefficient(curve, area)
                return value * walls if surface == "wall" else value
        return None

    def coefficient(surface: str, zone: str, sign: str) -> float | None:
        if surface == "roof" and zone == "3" and corner_as_edge:
            zone = "2"
        return curve_value(surface, zone, sign)

    zones = []
    for (surface, zone), label in CLADDING_ZONES.items():
        pos = coefficient(surface, zone, "positive")
        neg = coefficient(surface, zone, "negative")
        if pos is None and neg is None:
            continue
        zones.append(
            {
                "surface": surface,
                "zone": zone,
                "label": label,
                "GCpPos": pos,
                "GCpNeg": neg,
                "pPos_kPa": None if pos is None else qh * (pos + gcpi),
                "pNeg_kPa": None if neg is None else qh * (neg - gcpi),
            }
        )
    out: dict[str, Any] = {
        "h_m": height,
        "qh_kPa": qh,
        "lowRise": low,
        "a_m": cladding_edge_width(least, height, low),
        "area_m2": area,
        "enclosure": enclosure,
        "GCpi": gcpi,
        "zones": zones,
        "parapet": None,
    }
    if parapet:
        qp = velocity_pressure(height + parapet, speed, exposure, importance)
        wall_pos = curve_value("wall", "5", "positive") or 0.0
        wall_neg = curve_value("wall", "5", "negative") or 0.0
        roof = curve_value("roof", "3", "negative") or 0.0
        out["parapet"] = {
            "height_m": parapet,
            "qp_kPa": qp,
            "caseA_kPa": qp * (wall_pos - roof),
            "caseB_kPa": qp * (wall_pos - wall_neg),
        }
    return out


def slab_edge_loads(
    corners: list[tuple[float, float]], pressure: float, system: str
) -> list[EdgeProfile]:
    """The load shapes on a slab's edges carrying ``pressure`` on its area: triangles and
    trapezoids by the 45° rule (BNBC 2020 Part 6 Sec 6.5.6.8.1, p. 955), see
    :func:`saengine.fem.slab_load_shapes.slab_load_shapes`. ``EdgeProfile.load`` is the mean
    intensity (the uniform load of the same total this function gave before 0.0.45)."""
    return slab_load_shapes(corners, pressure, system).edges

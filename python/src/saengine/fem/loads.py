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


def damping_correction(damping: float | None = None) -> float:
    """The spectrum's damping correction η for the viscous damping ratio ``damping`` (of
    critical; None: the pack's reference damping), by the code pack's ``dampingCorrection``
    (``squareRoot``: η = √(numerator / (offset + 100ξ)), at least its minimum)."""
    seismic = code_context.table("seismic")
    rule = seismic.dampingCorrection
    if rule.method == "none" or damping is None or damping == rule.referenceDamping:
        return seismic.dampingEta
    eta = math.sqrt(rule.numerator / (rule.offset + 100.0 * float(damping)))
    return max(rule.minimum, eta)


def normalized_spectrum(period: float, site_class: str, damping: float | None = None) -> float:
    """Normalized acceleration response spectrum Cs(T) for the site class, with the damping
    correction η of the viscous damping ratio ``damping`` (None: the code's reference, 5 %)."""
    seismic = code_context.table("seismic")
    site = seismic.siteClasses[site_class]
    s, tb, tc, td = site.S, site.TB, site.TC, site.TD
    eta = damping_correction(damping)
    if period <= tb:
        return s * (1 + period / tb * (2.5 * eta - 1))
    if period <= tc:
        return 2.5 * s * eta
    if period <= td:
        return 2.5 * s * eta * tc / period
    return 2.5 * s * eta * tc * td / period**2


def design_acceleration(
    period: float,
    site_class: str,
    z: float,
    importance: float,
    r: float,
    damping: float | None = None,
) -> float:
    """Design spectral acceleration Sa = (2/3)·(Z·I/R)·Cs, as a fraction of g (``damping``:
    see :func:`normalized_spectrum`)."""
    return 2 / 3 * z * importance / r * normalized_spectrum(period, site_class, damping)


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
    CladdingCurve`, or :class:`~saengine.codes.tables.CladdingPointCurve` with its points) for
    the effective wind area ``area`` [m²], linear in log A between its areas; None: the
    smallest area's (the largest magnitude, a safe default)."""
    points = getattr(curve, "points", None) or [(curve.area1, curve.gcp1), (curve.area2, curve.gcp2)]
    if area is None or area <= points[0][0]:
        return float(points[0][1])
    for (a1, g1), (a2, g2) in pairwise(points):
        if area <= a2:
            t = math.log10(area / a1) / math.log10(a2 / a1)
            return float(g1 + (g2 - g1) * t)
    return float(points[-1][1])


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


#: The roof forms of the components-and-cladding settings (the code pack's ``cladding.roofs``
#: names them; ``stepped``, ``arched`` and ``dome`` have their own rules).
CLADDING_ROOF_FORMS = (
    "flat",
    "gable",
    "hip",
    "monoslope",
    "multispan",
    "sawtooth",
    "stepped",
    "arched",
    "dome",
)
#: The form whose figures every other form falls back on where it has none at its angle.
_CLADDING_BASE_FORM = "gable"


def cladding_roof_figure(form: str, theta: float) -> tuple[Any, str | None]:
    """(the code pack's roof figure of ``form`` at the roof angle θ [°], a note) for low-rise
    components and cladding: the figure whose forms include ``form`` with angleFrom < θ ≤
    angleTo (θ = 0 in the first); where ``form`` has none at θ, the base (gable) figure, with a
    note; (None, note) when there is none at all."""
    table = getattr(code_context.table("wind"), "cladding", None)
    roofs = list(getattr(table, "roofs", None) or [])

    def find(name: str) -> Any:
        return next(
            (
                r
                for r in roofs
                if name in r.forms
                and (r.angleFrom < theta <= r.angleTo or (theta <= 0 and r.angleFrom <= 0))
            ),
            None,
        )

    figure = find(form)
    if figure is not None:
        return figure, None
    base = find(_CLADDING_BASE_FORM)
    if base is None:
        return None, f"no components-and-cladding roof figure for a {form} roof at θ {theta:g}°"
    if form in ("flat", _CLADDING_BASE_FORM):
        return base, None
    return base, (
        f"{form} roof at θ {theta:g}°: outside its own figure's angles, the {_CLADDING_BASE_FORM} "
        f"roof figure ({base.source or 'the code pack'}) is used"
    )


def _curve_values(curves: list[Any], area: float | None) -> dict[str, dict[str, float]]:
    """zone -> {"positive": GCp, "negative": GCp} of the curves at ``area``."""
    out: dict[str, dict[str, float]] = {}
    for curve in curves:
        out.setdefault(curve.zone, {})[curve.sign] = cladding_coefficient(curve, area)
    return out


def _larger(a: float | None, b: float | None) -> float | None:
    """The one of larger magnitude."""
    if a is None or b is None:
        return a if b is None else b
    return a if abs(a) >= abs(b) else b


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
    opening_area: float | None = None,
    volume: float | None = None,
    roof_form: str = "flat",
    roof_angle: float | None = None,
    roof_rise: float | None = None,
    step_height: float | None = None,
) -> dict[str, Any] | None:
    """The design pressures of components and cladding by zone (BNBC 2020 Part 6 Sec 2.4.11.4)
    of a building of mean roof height ``height`` and least horizontal dimension ``least`` [m],
    for an effective wind area ``area`` [m²] (None: the smallest tabulated, the largest
    pressures) and the internal pressure of its ``enclosure``:

        p = qh·[(GCp) − (±GCpi)]  [kN/m²]   (Eq 6.2.24, h ≤ 18.3 m; Eq 6.2.25 above, q = qh on
                                             the leeward and side walls and the roof, qz on the
                                             windward wall, which is qh at the top: the pressures
                                             given are those at h, the largest)

    Positive towards the surface. The roof: ``roof_form`` (:data:`CLADDING_ROOF_FORMS`) at the
    angle ``roof_angle`` θ [°] takes the code pack's roof figure of that form and angle (gable,
    hip, monoslope, multispan, sawtooth; flat and gable up to 7° the flat-roof curves), with its
    overhang zones and rules (hip roofs: zone 3 as zone 2 up to the pack's angle); a taller
    building (h above the low-rise limit) with θ above the pack's ``highRiseRoofsFrom`` takes the
    same low-rise roof figures with qh. ``stepped``: the flat roof's zones, plus those of the lower
    level at the roof-upper wall intersection (``step_height`` h1 the upper part's height above
    it); ``arched``: the roof figure at the springline slope ``roof_angle`` at the perimeter and
    the arched roof Cp × the pack's factor elsewhere (``roof_rise`` r, rise to span); ``dome``:
    the dome table by the angle from the springline (``roof_rise`` f/D), q at the top
    (``height``). A parapet ``parapet`` m high, at least the code pack's 0.9 m, turns roof zone 3
    into zone 2 (flat roofs) and gives the roof zones the pack's wall positive (GCp); the
    parapet's own net pressures, at qp of its top, are Case A (windward: wall zone 5 positive on
    the front, roof zone 3 suction on the back) and Case B (leeward: wall positive on the back,
    wall zone 5 suction on the front) (Sec 2.4.11.5, Eq 6.2.26, a solid parapet, GCpi = 0).

    Returns ``{"h_m", "qh_kPa", "lowRise", "a_m", "area_m2", "enclosure", "GCpi", "Ri",
    "roofForm", "theta_deg", "figure", "zones": [{"surface", "zone", "label", "GCpPos",
    "GCpNeg", "pPos_kPa", "pNeg_kPa"}], "parapet", "notes"}``; None when the code pack has no
    cladding table. ``opening_area`` Aog [m²] and ``volume`` Vi [m³]: the reduction Ri of a
    partially enclosed building with one unpartitioned volume
    (:func:`internal_pressure_coefficient`)."""
    table = getattr(code_context.table("wind"), "cladding", None)
    if table is None:
        return None
    theta = float(roof_angle or 0.0)
    form = roof_form if roof_form in CLADDING_ROOF_FORMS else "flat"
    notes: list[str] = []
    low = height <= table.lowRiseHeight
    gcpi_full, ri = internal_pressure_coefficient(enclosure, opening_area, volume)
    gcpi = gcpi_full * ri
    qh = velocity_pressure(height, speed, exposure, importance)
    wall_factor = (
        table.lowRiseWallFactor
        if low and (table.wallFactorMaxAngle is None or theta <= table.wallFactorMaxAngle)
        else 1.0
    )
    has_parapet = parapet is not None and parapet >= table.parapetCorner

    walls = _curve_values(
        [c for c in (table.lowRise if low else table.highRise) if c.surface == "wall"], area
    )
    walls = {z: {s: v * wall_factor for s, v in vs.items()} for z, vs in walls.items()}
    flat_roof = [c for c in (table.lowRise if low else table.highRise) if c.surface == "roof"]

    # The roof's zones: label, positive, negative (None where none is given).
    roof: list[tuple[str, str, float | None, float | None]] = []
    figure_source = None
    low_figures = (
        low
        or form == "arched"
        or (table.highRiseRoofsFrom is not None and theta > table.highRiseRoofsFrom)
    )
    if not low and low_figures and form not in ("dome",):
        notes.append(
            f"h {height:.1f} m above {table.lowRiseHeight:g} m with a roof θ {theta:g}°: the "
            "low-rise roof figures with qh"
        )

    def figure_zones(figure_form: str, angle: float, suffix: str = "") -> None:
        nonlocal figure_source
        figure, note = cladding_roof_figure(figure_form, angle)
        if note:
            notes.append(note)
        if figure is None:
            return
        figure_source = figure_source or figure.source
        if figure.note:
            notes.append(figure.note)
        values = _curve_values(figure.roof or flat_roof, area)
        if figure.envelopeForm:
            other, _ = cladding_roof_figure(figure.envelopeForm, angle)
            if other is not None and other is not figure:
                more = _curve_values(other.roof or flat_roof, area)
                for zone, vs in values.items():
                    base = more.get(zone) or more.get(zone.rstrip("'A")) or {}
                    for sign in ("positive", "negative"):
                        vs[sign] = _larger(vs.get(sign), base.get(sign))
        corner_to = figure.cornerAsEdge.get(form)
        if corner_to is not None and angle <= corner_to and "3" in values and "2" in values:
            values["3"] = dict(values["2"])
            notes.append(f"{form} roof θ ≤ {corner_to:g}°: zone 3 treated as zone 2")
        if has_parapet and figure.parapetCornerAsEdge and "3" in values:
            if "2" in values and "negative" in values["2"]:
                values["3"]["negative"] = values["2"]["negative"]
            for roof_zone, wall_zone in table.parapetPositive.items():
                if roof_zone in values and walls.get(wall_zone, {}).get("positive") is not None:
                    values[roof_zone]["positive"] = walls[wall_zone]["positive"]
        labels = {**CLADDING_ROOF_LABELS, **figure.zoneLabels}
        for zone, vs in values.items():
            label = labels.get(zone, f"roof, zone {zone}")
            roof.append((zone + suffix, label, vs.get("positive"), vs.get("negative")))
        if not suffix:
            for zone, vs in _curve_values(figure.overhang, area).items():
                label = labels.get(zone, f"zone {zone}").replace("roof, ", "")
                roof.append(
                    (f"{zone} overhang", f"roof overhang, {label}", None, vs.get("negative"))
                )

    if form == "dome":
        dome = table.domes
        if dome is None:
            notes.append("the code pack has no dome components-and-cladding table")
        else:
            figure_source = dome.source
            lo, hi = dome.riseRange
            if roof_rise is not None and not lo <= roof_rise <= hi:
                notes.append(
                    f"dome f/D {roof_rise:g} outside the table's {lo:g}-{hi:g} (hD/D up to "
                    f"{dome.baseMax:g}): the values are used as printed"
                )
            start = 0.0
            for upto, value in dome.positive:
                roof.append(
                    (
                        f"dome {start:g}-{upto:g}°",
                        f"dome, {start:g}° to {upto:g}° from the springline",
                        float(value),
                        float(dome.negative),
                    )
                )
                start = float(upto)
    elif not low_figures:
        figure_source = None
        values = _curve_values(flat_roof, area)
        if has_parapet and "3" in values and "2" in values:
            values["3"]["negative"] = values["2"]["negative"]
        for zone, vs in values.items():
            label = CLADDING_ROOF_LABELS.get(zone, f"roof, zone {zone}")
            roof.append((zone, label, vs.get("positive"), vs.get("negative")))
    elif form == "arched":
        figure_zones(_CLADDING_BASE_FORM, theta, " perimeter")
        arched = table.arched
        cps = arched_roof_cps(roof_rise, True) if roof_rise is not None else None
        if arched is None or cps is None:
            notes.append(
                "arched roof: no rise-to-span ratio r in the table's range (or no arched "
                "table): the perimeter values only"
            )
        else:
            factor = float(arched.interiorFactor)
            parts = [
                ("windward quarter", min(cps["windward"])),
                ("centre half", cps["centre"]),
                ("leeward quarter", cps["leeward"]),
            ]
            for name, cp in parts:
                value = factor * float(cp)
                roof.append(
                    (
                        f"arch {name}",
                        f"arched roof, {name} (Cp × {factor:g})",
                        value if value > 0 else None,
                        value if value <= 0 else None,
                    )
                )
    else:
        figure_zones(form, theta)
        if form == "stepped":
            _stepped_zones(table, roof, walls, height, step_height, notes)

    zones = []
    for zone, label in (("4", CLADDING_ZONES[("wall", "4")]), ("5", CLADDING_ZONES[("wall", "5")])):
        vs = walls.get(zone)
        if vs:
            zones.append(("wall", zone, label, vs.get("positive"), vs.get("negative")))
    zones += [("roof", z, label, pos, neg) for z, label, pos, neg in roof]
    q_roof = qh  # the dome's q is at its top: ``height`` is taken as that
    out_zones = [
        {
            "surface": surface,
            "zone": zone,
            "label": label,
            "GCpPos": pos,
            "GCpNeg": neg,
            "pPos_kPa": None if pos is None else q_roof * (pos + gcpi),
            "pNeg_kPa": None if neg is None else q_roof * (neg - gcpi),
        }
        for surface, zone, label, pos, neg in zones
    ]
    out: dict[str, Any] = {
        "h_m": height,
        "qh_kPa": qh,
        "lowRise": low,
        "a_m": cladding_edge_width(least, height, low),
        "area_m2": area,
        "enclosure": enclosure,
        "GCpi": gcpi,
        "Ri": ri,
        "roofForm": form,
        "theta_deg": theta,
        "figure": figure_source,
        "zones": out_zones,
        "parapet": None,
        "notes": notes,
    }
    if parapet:
        qp = velocity_pressure(height + parapet, speed, exposure, importance)
        wall_pos = walls.get("5", {}).get("positive") or 0.0
        wall_neg = walls.get("5", {}).get("negative") or 0.0
        flat = _curve_values(flat_roof, area)
        roof_neg = flat.get("3", {}).get("negative") or 0.0
        out["parapet"] = {
            "height_m": parapet,
            "qp_kPa": qp,
            "caseA_kPa": qp * (wall_pos - roof_neg),
            "caseB_kPa": qp * (wall_pos - wall_neg),
        }
    return out


#: What each roof zone of the flat and gable roof figures is.
CLADDING_ROOF_LABELS = {
    "1": CLADDING_ZONES[("roof", "1")],
    "2": CLADDING_ZONES[("roof", "2")],
    "3": CLADDING_ZONES[("roof", "3")],
}


def _stepped_zones(
    table: Any,
    roof: list[tuple[str, str, float | None, float | None]],
    walls: dict[str, dict[str, float]],
    height: float,
    step_height: float | None,
    notes: list[str],
) -> None:
    """The lower level of a flat stepped roof (the pack's ``cladding.stepped``): at the
    roof-upper wall intersection its zones take those of the pack's zone map (3 as 2, 2 as 1),
    and a strip b = 1.5·h1 (≤ the pack's limit) wide the walls' positive (GCp)."""
    stepped = table.stepped
    if stepped is None:
        notes.append("the code pack has no stepped roof rule: the flat roof's zones only")
        return
    by_zone = {z: (pos, neg) for z, _, pos, neg in roof}
    for source, target in stepped.zoneMap.items():
        if target in by_zone and source in by_zone:
            pos, neg = by_zone[target]
            roof.append(
                (
                    f"{source} step",
                    f"lower roof at the upper wall: zone {source} treated as zone {target}",
                    pos,
                    neg,
                )
            )
    wall_pos = max(
        (vs["positive"] for vs in walls.values() if vs.get("positive") is not None), default=None
    )
    if step_height is None or step_height <= 0:
        notes.append("stepped roof: no step height h1 given, so the strip width b is not set")
        width = None
    else:
        width = min(stepped.widthFactor * step_height, stepped.widthMax)
        ratio = step_height / height if height > 0 else 0.0
        lo, hi = stepped.heightRatio
        if step_height < stepped.minUpperHeight or not (lo <= ratio <= hi and lo <= 1 - ratio <= hi):
            notes.append(
                f"stepped roof h1 {step_height:g} m, h1/h {ratio:.2f}: outside the figure's "
                f"limits (h1 ≥ {stepped.minUpperHeight:g} m, hi/h {lo:g}-{hi:g}); used as printed"
            )
        w_lo, w_hi = stepped.widthRatio
        notes.append(f"stepped roof: the figure needs Wi/W {w_lo:g}-{w_hi:g} (not checked here)")
    interior = by_zone.get("1", (None, None))[1]
    roof.append(
        (
            "step strip",
            "lower roof strip at the upper wall"
            + (f", b = {width:.2f} m wide" if width is not None else "")
            + ": the walls' positive (GCp)",
            wall_pos,
            interior,
        )
    )


# ─────────── wind: internal pressure and the MWFRS pressures on walls and roofs ───────────
#
# The code pack's ``wind.internalPressure`` and ``wind.mwfrs`` (BNBC 2020 Part 6 Sec 2.4.10,
# 2.4.11.2, Figures 6.2.5-6.2.8 and 6.2.10). Positive pressures act toward the surface.


def internal_pressure_coefficient(
    enclosure: str, opening_area: float | None = None, volume: float | None = None
) -> tuple[float, float]:
    """(GCpi, Ri): the internal pressure coefficient's magnitude of the ``enclosure``
    classification (Sec 2.4.10.1, Figure 6.2.5) and the reduction factor of a partially
    enclosed building with one unpartitioned large volume (Eq 6.2.18, p. 556):

        Ri = 0.5·(1 + 1/√(1 + Vi/(6951·Aog))) ≤ 1.0

    with Aog = ``opening_area`` the total area of openings in the envelope [m²] and Vi =
    ``volume`` the unpartitioned internal volume [m³]; Ri = 1 when either is not given or the
    enclosure is not one the pack reduces. (0, 1) when the code pack has no coefficients."""
    wind = code_context.table("wind")
    table = getattr(wind, "internalPressure", None)
    if table is None:
        cladding = getattr(wind, "cladding", None)
        coefficients = (getattr(cladding, "internal", None) or {}) if cladding else {}
        return float(coefficients.get(enclosure, 0.0)), 1.0
    gcpi = float(table.coefficients.get(enclosure, 0.0))
    if (
        enclosure not in table.reducedEnclosures
        or not opening_area
        or not volume
        or opening_area <= 0
        or volume <= 0
    ):
        return gcpi, 1.0
    ri = table.reductionBase * (1 + 1 / math.sqrt(1 + volume / (table.volumeFactor * opening_area)))
    return gcpi, min(1.0, ri)


def mwfrs_table() -> Any:
    """The code pack's MWFRS wall and roof table, None without one."""
    return getattr(code_context.table("wind"), "mwfrs", None)


def _interpolate(x: float, xs: list[float], ys: list[float]) -> float:
    """Linear interpolation, the end values beyond the ends."""
    if x <= xs[0]:
        return ys[0]
    for (x0, y0), (x1, y1) in pairwise(zip(xs, ys, strict=True)):
        if x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return ys[-1]


def _across_rows(rows: list[Any], ratio: float, value: Any) -> Any:
    """``value(row)`` interpolated between the rows by their ``hOverL`` (each value a number or
    a tuple of numbers), the end rows beyond the ends."""
    keys = [float(r.hOverL) for r in rows]
    values = [value(r) for r in rows]
    if isinstance(values[0], tuple):
        return tuple(
            _interpolate(ratio, keys, [v[k] for v in values]) for k in range(len(values[0]))
        )
    return _interpolate(ratio, keys, values)


def roof_windward_cp(theta: float, h_over_l: float) -> tuple[float, float]:
    """(first, second) Cp of a windward roof slope θ [°] for wind normal to the ridge (Figure
    6.2.6, p. 572): where two values are listed the roof is designed for both (note 3), else
    both are the one value. Linear between angles and h/L ratios, between values of the same
    column (note 2: a value not printed counts 0.0); Cp = 0.01θ from 60° and 0.8 above 80° (the
    pack's ``steepFrom``, ``verticalFrom``)."""
    table = mwfrs_table().roof
    if theta > table.verticalFrom:
        return float(table.verticalCp), float(table.verticalCp)
    if theta >= table.steepFrom:
        v = table.steepFactor * theta
        return v, v
    angles = [float(a) for a in table.angles]

    def column(values: list[float | None]) -> list[float]:
        return [
            table.steepFactor * a if a >= table.steepFrom else (0.0 if v is None else float(v))
            for a, v in zip(angles, values, strict=True)
        ]

    def row(r: Any) -> tuple[float, float]:
        first = column(r.first)
        second = column(r.second) if r.second is not None else first
        return _interpolate(theta, angles, first), _interpolate(theta, angles, second)

    return _across_rows(table.windward, h_over_l, row)


def roof_leeward_cp(theta: float, h_over_l: float) -> float:
    """Cp of a leeward roof slope θ [°] for wind normal to the ridge (Figure 6.2.6, p. 572)."""
    table = mwfrs_table().roof
    angles = [float(a) for a in table.leewardAngles]
    return _across_rows(
        table.leeward,
        h_over_l,
        lambda r: _interpolate(theta, angles, [float(v or 0.0) for v in r.first]),
    )


def _area_reduction(table: Any, area: float | None) -> float:
    """The factor on the reducible roof Cp (Figure 6.2.6, **) for the ``area`` [m²] it acts
    over, linear between the pack's points; 1 when not given."""
    points = table.areaReduction
    if area is None or not points:
        return 1.0
    return _interpolate(area, [p[0] for p in points], [p[1] for p in points])


def roof_parallel_cp(
    distance: float, height: float, h_over_l: float, area: float | None = None
) -> tuple[float, float]:
    """(first, second) Cp of a roof point ``distance`` [m] from the windward edge, for a roof
    θ < 10° or wind parallel to the ridge (Figure 6.2.6, p. 572): by zones of the mean roof
    height ``height`` h, interpolated between h/L rows. ``area`` [m²]: of the first zone, which
    reduces the -1.3 value (**)."""
    table = mwfrs_table().roof

    def row(r: Any) -> tuple[float, float]:
        ratio = distance / height if height > 0 else math.inf
        zone = next((z for z in r.zones if z.upTo is None or ratio <= z.upTo), r.zones[-1])
        values = [float(v) for v in zone.cp]
        if table.reducible is not None and values[0] == table.reducible:
            values[0] *= _area_reduction(table, area)
        return values[0], values[-1]

    return _across_rows(table.parallel, h_over_l, row)


def dome_point_cps(rise_ratio: float, base_ratio: float) -> dict[str, float] | None:
    """Cp at A (windward springline), B (top) and C (leeward springline) of a dome of f/D
    ``rise_ratio`` on a base hD/D ``base_ratio`` (Figure 6.2.7, p. 573: the curves read
    from the figure, linear between hD/D curves); None below the figure's least f/D (note 8:
    Figure 6.2.6 instead) or without the pack's dome table."""
    table = getattr(mwfrs_table(), "domes", None)
    if table is None or rise_ratio < table.minRise:
        return None

    def at(curves: list[Any]) -> float:
        keys = [float(c.hdOverD) for c in curves]
        values = [
            _interpolate(rise_ratio, [p[0] for p in c.points], [p[1] for p in c.points])
            for c in curves
        ]
        return _interpolate(base_ratio, keys, values)

    return {"A": at(table.A), "B": at(table.B), "C": at(table.C)}


def dome_cp(cps: dict[str, float], theta: float, windward: bool, case: str) -> float:
    """Cp of a dome point at θ [°] along its arc parallel to the wind (0 at the springline, 90
    at the top), on the windward (A to B) or leeward (C to B) side (Figure 6.2.7, note 1): Case
    A linear along the arcs; Case B the constant A up to 25° (the pack's ``caseBAngle``), then
    linear to B; the leeward side linear from B to C in both."""
    theta = min(max(theta, 0.0), 90.0)
    if not windward:
        return cps["C"] + (cps["B"] - cps["C"]) * theta / 90
    if case == "B":
        start = float(mwfrs_table().domes.caseBAngle)
        if theta <= start:
            return cps["A"]
        return cps["A"] + (cps["B"] - cps["A"]) * (theta - start) / (90 - start)
    return cps["A"] + (cps["B"] - cps["A"]) * theta / 90


def arched_roof_cps(rise_ratio: float, elevated: bool) -> dict[str, Any] | None:
    """Cp of an arched roof of rise-to-span ``rise_ratio`` r (Figure 6.2.8, p. 574):
    ``windward`` (the windward quarter's values: the alternate (6r − 2.1) too where it shall
    also be used), ``centre`` (the centre half) and ``leeward`` (the leeward quarter); None
    outside the table's r or without the pack's arched table."""
    table = getattr(mwfrs_table(), "arched", None)
    if table is None:
        return None
    rows = [r for r in table.rows if r.elevated == elevated]
    row = next(
        (r for r in rows if r.riseFrom <= rise_ratio < r.riseTo),
        next((r for r in rows if math.isclose(rise_ratio, r.riseTo)), None),
    )
    if row is None:
        return None
    windward = [row.windward[0] * rise_ratio + row.windward[1]]
    if row.alternate is not None:
        windward.append(row.alternate[0] * rise_ratio + row.alternate[1])
    return {
        "windward": windward,
        "centre": table.centre[0] * rise_ratio + table.centre[1],
        "leeward": float(table.leeward),
    }


def low_rise_gcpf(theta: float) -> dict[str, float] | None:
    """(GCpf) by building surface (1-6, 1E-4E) of a low-rise building with roof angle θ [°]
    (Figure 6.2.10, p. 577, linear between angles, note 2); None without the pack's table."""
    table = getattr(mwfrs_table(), "lowRise", None)
    if table is None:
        return None
    rows = sorted(table.rows, key=lambda r: r.angle)
    angles = [float(r.angle) for r in rows]
    return {
        surface: _interpolate(theta, angles, [float(r.gcpf[surface]) for r in rows])
        for surface in rows[0].gcpf
    }


def is_low_rise(height: float, least: float) -> bool:
    """Whether an enclosed or partially enclosed building is low-rise (Sec 2.1.3, p. 513):
    mean roof height h up to the pack's 18.3 m and not over its least horizontal dimension."""
    table = getattr(mwfrs_table(), "lowRise", None)
    return table is not None and height <= table.maxHeight and height <= least


def mean_roof_height(eave: float, top: float, theta: float) -> float:
    """h of Figures 6.2.6 and 6.2.10 (notation): the mean of the eave and the top of the roof,
    the eave height for θ ≤ 10° (the pack's ``flatAngle``)."""
    mwfrs = mwfrs_table()
    flat = float(mwfrs.roof.flatAngle) if mwfrs is not None else 0.0
    return eave if theta <= flat else (eave + top) / 2


def building_mwfrs_pressures(
    height: float,
    depth: float,
    width: float,
    speed: float,
    exposure: str,
    importance: float,
    *,
    enclosure: str = "enclosed",
    opening_area: float | None = None,
    volume: float | None = None,
) -> dict[str, Any] | None:
    """The MWFRS design pressures p = q·G·Cp − qh·(±GCpi) (Eq 6.2.19, p. 557) on the walls and
    the flat roof (θ < 10°) of a building of mean roof height ``height`` h, ``depth`` L along
    the wind and ``width`` B across it [m] (Figure 6.2.6): windward wall at h (qz, the largest),
    leeward and side walls and the roof zones by distance from the windward edge at qh. Returns
    ``{"qh_kPa", "G", "GCpi", "Ri", "hOverL", "surfaces": [{"surface", "from_m", "to_m", "Cp",
    "pPos_kPa", "pNeg_kPa"}]}`` (``pPos``/``pNeg``: with −GCpi/+GCpi, the external Cp the
    larger in magnitude where two are listed); None without the pack's MWFRS table."""
    mwfrs = mwfrs_table()
    if mwfrs is None or height <= 0 or depth <= 0 or width <= 0:
        return None
    qh = velocity_pressure(height, speed, exposure, importance)
    gust = wind_factor("gust")
    wind = code_context.table("wind")
    gcpi, ri = internal_pressure_coefficient(enclosure, opening_area, volume)
    inner = gcpi * ri * qh
    ratio = height / depth
    rows: list[dict[str, Any]] = []

    def add(surface: str, cp: float, start: float | None = None, end: float | None = None) -> None:
        external = qh * gust * cp
        rows.append(
            {
                "surface": surface,
                "from_m": start,
                "to_m": end,
                "Cp": cp,
                "pPos_kPa": external + inner,
                "pNeg_kPa": external - inner,
            }
        )

    add("windward wall", float(wind.cpWindward))
    add("leeward wall", leeward_coefficient(depth / width))
    add("side wall", float(mwfrs.sideWall))
    zone_area = min(height / 2, depth) * width
    edges = sorted({0.0, *(min(f * height, depth) for f in (0.5, 1.0, 2.0)), depth})
    for start, end in pairwise(edges):
        if end - start <= 1e-9:
            continue
        first, _ = roof_parallel_cp((start + end) / 2, height, ratio, zone_area)
        add("roof", first, start, end)
    return {
        "qh_kPa": qh,
        "G": gust,
        "GCpi": gcpi,
        "Ri": ri,
        "hOverL": ratio,
        "surfaces": rows,
    }


# ─────────── wind: the load cases of clad structures (directions, variants, internal) ───────────

#: The wind case of the opposite direction (−X, −Y) of a structure whose pressures are not
#: symmetric (roofs, :mod:`saengine.fem.open_wind` clad structures): a combination's −WX takes
#: WXN at +1, not WX at −1.
WIND_OPPOSITE_CASES = {"WX": "WXN", "WY": "WYN"}
#: The internal pressure case: (GCpi)·Ri·qh toward the internal surfaces of the envelope
#: (outward), taken by the combinations with ± (Figure 6.2.5, note 3).
WIND_INTERNAL_CASE = "WI"
#: At most this many external pressure variants per wind direction (WX, WX2, ...).
WIND_MAX_VARIANTS = 9


def wind_variant_case(direction: str, variant: int) -> str:
    """The name of external pressure variant ``variant`` (1, 2, ...) of the wind case
    ``direction`` (WX, WXN, WY, WYN): the case itself for 1, else ``<case><variant>``."""
    return direction if variant <= 1 else f"{direction}{variant}"


def wind_pressure_cases() -> list[str]:
    """Every case name the clad structures' wind may add after WX and WY, in order."""
    out = []
    for base in ("WX", "WXN", "WY", "WYN"):
        out += [wind_variant_case(base, k) for k in range(1, WIND_MAX_VARIANTS + 1)]
    return [c for c in out if c not in ("WX", "WY")] + [WIND_INTERNAL_CASE]


def resolve_wind_cases(
    variants: list[tuple[str, dict[str, float]]], present: set[str] | frozenset[str]
) -> list[tuple[str, dict[str, float]]]:
    """The design wind variants (:func:`wind_design_variants`) on the cases the model has: a
    negative factor on WX or WY goes to the opposite direction's case (WXN, WYN) at its
    magnitude where the model has it; each direction's external pressure variants (WX2, ...)
    each give a row; and with the internal pressure case WI, each row twice, with ±WI at the
    largest wind factor's magnitude (Figure 6.2.5, note 3). A model with none of these cases
    gets ``variants`` unchanged."""
    if not any(c in present for c in wind_pressure_cases()):
        return variants
    internal = WIND_INTERNAL_CASE in present
    out: list[tuple[str, dict[str, float]]] = []
    for label, factors in variants:
        rows: list[tuple[str, dict[str, float]]] = [("", {})]
        for direction in ("WX", "WY"):
            f = factors.get(direction, 0.0)
            if not f:
                continue
            opposite = WIND_OPPOSITE_CASES[direction]
            base, value = (opposite, -f) if f < 0 and opposite in present else (direction, f)
            names = [base] + [
                wind_variant_case(base, k)
                for k in range(2, WIND_MAX_VARIANTS + 1)
                if wind_variant_case(base, k) in present
            ]
            named = base != direction or len(names) > 1
            rows = [
                (text + (f" {name}" if named else ""), {**row, name: value})
                for text, row in rows
                for name in names
            ]
        rest = {k: v for k, v in factors.items() if k not in ("WX", "WY")}
        for text, row in rows:
            merged = {**rest, **row}
            if internal and row:
                magnitude = max(abs(v) for v in row.values())
                for sign, mark in ((1.0, "+"), (-1.0, "-")):
                    out.append(
                        (
                            f"{label}{text} {mark}{WIND_INTERNAL_CASE}".strip(),
                            {**merged, WIND_INTERNAL_CASE: sign * magnitude},
                        )
                    )
            else:
                out.append((f"{label}{text}".strip(), merged))
    return out


def slab_edge_loads(
    corners: list[tuple[float, float]], pressure: float, system: str
) -> list[EdgeProfile]:
    """The load shapes on a slab's edges carrying ``pressure`` on its area: triangles and
    trapezoids by the 45° rule (BNBC 2020 Part 6 Sec 6.5.6.8.1, p. 955), see
    :func:`saengine.fem.slab_load_shapes.slab_load_shapes`. ``EdgeProfile.load`` is the mean
    intensity (the uniform load of the same total this function gave before 0.0.45)."""
    return slab_load_shapes(corners, pressure, system).edges

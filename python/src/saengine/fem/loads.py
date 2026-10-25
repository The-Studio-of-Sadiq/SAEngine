"""Loads of the analysis model from the project settings (BNBC 2020 Part 6 Chapter 2).

Pure functions: given the building's levels, weights and plan, they return the equivalent
static seismic and wind forces per level and the beam loads of slab areas. The derivation of the
analysis model (:mod:`saengine.fem.derive`) applies them; every formula names its clause, and
the code pack in force (:func:`saengine.codes.context.current`, BNBC 2020 by default) holds
the coefficients.

Units: m, kN, s.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

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


def exposure_coefficient(height: float, exposure: str) -> float:
    """Velocity pressure exposure coefficient Kz at ``height`` metres (Table 6.2.11)."""
    profile = code_context.table("wind").exposures[exposure]
    alpha, zg = profile.alpha, profile.zg
    return 2.01 * (max(height, 4.57) / zg) ** (2 / alpha)


def velocity_pressure(height: float, speed: float, exposure: str, importance: float) -> float:
    """qz = 0.000613·Kz·Kzt·Kd·V²·I [kN/m²], V in m/s."""
    wind = code_context.table("wind")
    return (
        0.000613
        * exposure_coefficient(height, exposure)
        * wind.topographic
        * wind.directionality
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
        return qh * wind.gust * leeward_coefficient(depths[i] / width)

    out = []
    for i, z in enumerate(heights):
        windward = velocity_pressure(z, speed, exposure, importance) * wind.gust * wind.cpWindward
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


def slab_edge_loads(
    corners: list[tuple[float, float]], pressure: float, system: str
) -> list[EdgeProfile]:
    """The load shapes on a slab's edges carrying ``pressure`` on its area: triangles and
    trapezoids by the 45° rule (BNBC 2020 Part 6 Sec 6.5.6.8.1, p. 955), see
    :func:`saengine.fem.slab_load_shapes.slab_load_shapes`. ``EdgeProfile.load`` is the mean
    intensity (the uniform load of the same total this function gave before 0.0.45)."""
    return slab_load_shapes(corners, pressure, system).edges

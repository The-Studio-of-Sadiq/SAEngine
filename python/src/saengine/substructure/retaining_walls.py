"""Retaining and basement walls (Part 9): stability and RC design per metre run.

Each wall of ``09 Substructure/substructure.json`` ``retainingWalls`` is designed on the soil
of 1 Soil Report at the middle of its path (the nearest borehole's layers, linked through
:func:`saengine.substructure.earth_pressure.soil_column`; a ``backfill`` replaces them behind
the wall). The pressures come from the one earth-pressure engine,
:mod:`saengine.substructure.earth_pressure`. :func:`design_retaining_wall` is the entry point;
:func:`saengine.substructure.report.report` lists the walls with the foundations.

Geometry (a section across the wall, metres): the base ``toe + stem + heel`` wide and
``baseThickness`` thick, its underside at ``foundingLevel``; the stem from the top of the base
to ``topLevel``, ``stemBottom`` thick at the base and ``stemTop`` at the top, its soil face
vertical (the batter on the front face). The retained ground is at ``retainedLevel`` (the
finished ground by default), the ground in front at ``frontLevel`` (the top of the base by
default). The depths of the soil column are measured from the retained ground.

Loads (per metre run; BNBC 2020 Part 6 Sec 2.6.5 (p680))
- H, the lateral earth and water pressure (:mod:`saengine.substructure.earth_pressure`): on a
  cantilever wall active by default, on the vertical plane through the heel's end down to the
  underside of the base (Rankine, inclined at the backfill slope β; or Coulomb, at the wall
  friction δ), with the surcharge q; on a basement wall at rest on the stem. Below the design
  water table the soil is submerged and the full hydrostatic pressure added (Sec 2.6.5.1); a
  ``drained`` wall carries no water.
- uplift under the base (Sec 2.6.5.2, p680): the water pressure at the underside, linear from
  the heel (retained side) to the toe (the water no higher than the front ground there), and
  the water in front pushing back on the toe.
- D: the concrete (``concreteUnitWeight`` 24 kN/m³), the soil over the heel (total unit
  weight: γ, γsat below the water table) and over the toe; the surcharge over the heel counts
  only where it does not help (bearing, the heel's design).
- E (``seismic``): the increment of :func:`saengine.substructure.earth_pressure.seismic_increment`
  at the site's peak ground acceleration (2/3) Z S (BNBC 2020 Part 6 Sec 2.5.4.3), with the
  inertia of the wall (kh times its weight).

Stability of a cantilever wall (service loads; factors from the code pack's
``foundations.retainingWall``, see its sources)
- sliding: ``FS = (μ ΣV + ca B + Pp / FSp + Pw,front) / ΣH`` with μ the pack's fixed friction
  factor (0.5 in the default pack; the wall's verified value instead when given; without one
  in the pack: tan(r φ') of the soil under the base and ca = r cu on a clay without φ'), Pp the
  passive resistance in front, counted only when the wall states the soil in front cannot be
  removed (``passive``), ΣV net of the uplift;
- overturning about the toe: ``FS = ΣM_resisting / ΣM_overturning`` (the uplift overturns);
- the least factors of the pack (1.5 and 1.5 in the default pack, also with earthquake);
- bearing: the base pressure (linear, no tension) against the net allowable bearing pressure
  qa of 1 Soil Report at the founding level and the base width
  (:class:`saengine.substructure.shallow.SoilBearing`), less the overburden of the front side;
  the resultant within the middle third (flagged when outside).

Basement walls (``kind`` "basement") are propped by the floors at ``supports`` and fixed (or
pinned) at the raft: a one-way vertical span at rest, solved as a continuous beam
(:func:`beam_actions`); their stability is the building's, and the flotation of the basement
is checked once for all of them (:func:`flotation`).

RC design per metre run (strength: ACI 318-19, which BNBC 2020 Part 6 Chapter 6 adopts)
- combinations (BNBC 2020 Part 6 Sec 2.7.3.1, p685): 1.2D + 1.6H + 1.6L (the surcharge as L)
  and 0.9D + 1.6H for the base (the envelope of the two), 1.6H for the stem; with earthquake
  0.9D + 1.0E + 1.6H (ASCE 7-05 2.3.2 (7)). The uplift with the water pressure (1.6H).
- flexure: the ACI rectangular block (:func:`saengine.plumbing.tanks.flexure_area`) at the
  stem's base (and the supports and spans of a basement wall), the heel's top at the stem's
  back face, the toe's bottom at its front face;
- one-way shear without shear reinforcement (ACI 318-19 Table 22.5.5.1 (c),
  :func:`saengine.design.slab.one_way_shear`): the stem d above the base (d from the supports),
  the toe d from the stem, the heel at the stem's face (a support in tension);
- minimum: BNBC 2020 Part 6 Sec 6.6.3.2 / 6.6.3.3 (walls: vertical 0.0012 / 0.0015,
  horizontal 0.0020 / 0.0025 of the gross section, p969), ACI 318-19 7.6.1.1 for the base;
- crack control (service: D + H + L): the crack width of EN 1992-1-1:2004 7.3.4 at the soil
  face (:func:`saengine.plumbing.tanks.crack_width`) against ``crackLimit`` (0.3 mm; 0.2 mm
  watertight, EN 1992-3 Table 7.105) and the ACI 318-19 Table 24.3.2 spacing
  ``s ≤ 380 (280/fs) - 2.5 cc ≤ 300 (280/fs)`` with fs = 2/3 fy;
- cover: 50 mm (``reinforcement.cover``) at the stem, 75 mm under the base (BNBC 2020 Part 6
  Sec 8.1.7.2 (a), cast against earth);
- bars: the wall's ``reinforcement`` where given, else proposed (the lightest of 10-25 mm bars
  at 100-300 mm that gives the strength, the minimum and the crack width).

Units: the wall dict in mm; kN, kPa, kN·m/m, kN/m, mm²/m, mm reported.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design.check import _check
from saengine.design.rc import STEEL_E, bar_area
from saengine.design.slab import min_steel_ratio, one_way_shear
from saengine.substructure.context import Context, Skip
from saengine.substructure.earth_pressure import (
    GAMMA_W,
    STATES,
    Soil,
    seismic_increment,
    soil_column,
)

#: Unit weight of reinforced concrete [kN/m³] (BNBC 2020 Part 6 Table 6.2.1, p521: 23.6;
#: 24 as the tanks).
CONCRETE_UNIT_WEIGHT = 24.0
#: BNBC 2020 Part 6 Sec 8.1.7.2 (a): cast against and permanently exposed to earth [mm].
COVER_UNDER_BASE = 75.0
#: Bars the proposal tries [mm] and the spacings [mm].
DIAS = (10.0, 12.0, 16.0, 20.0, 25.0)
SPACINGS = (300.0, 250.0, 200.0, 175.0, 150.0, 125.0, 100.0)

METHOD = [
    (
        "Retaining and basement walls: per metre run; earth pressure from the one engine "
        "(at rest K0 = 1 - sin φ', active Rankine/Coulomb, passive Rankine; submerged soil and "
        "full hydrostatic pressure below the design water table, BNBC 2020 Part 6 Sec 2.6.5.1, "
        "uplift Sec 2.6.5.2, p680); soil from the nearest borehole of 1 Soil Report."
    ),
    (
        "Seismic earth pressure: Mononobe-Okabe (kh = ½ PGA, increment at 0.6 H, Seed & Whitman) "
        "on cantilever walls, Wood (kh = PGA, uniform) on basement walls; PGA = (2/3) Z S."
    ),
    (
        "Stability of cantilever walls: sliding and overturning against the code pack's least "
        "factors of safety (the same with earthquake), base friction by the pack's friction "
        "factor, passive resistance only where the soil in front cannot be removed; bearing "
        "against qa of 1 Soil Report, resultant in the middle third; flotation of the "
        "basement with the pack's factor on the dead load."
    ),
    (
        "Stem and base: ACI 318-19 flexure and one-way shear (Table 22.5.5.1), 1.6H (BNBC 2020 Part 6 "
        "Sec 2.7.3.1), BNBC 6.6.3.2-6.6.3.3 wall minimum, crack width EN 1992-1-1 7.3.4 and the "
        "ACI 318-19 Table 24.3.2 spacing."
    ),
]


def _factors() -> Any:
    """The pack's ``foundations.retainingWall`` factors."""
    return code_context.table("foundations").retainingWall


# ───────────────────────────────────── geometry ─────────────────────────────────────


@dataclass
class Section:
    """A wall's cross-section [m] and its levels relative to the retained ground."""

    toe: float
    heel: float
    stem_top: float
    stem_bottom: float
    base: float  # thickness
    stem_height: float  # from the top of the base to the top of the stem
    retained_depth: float  # from the retained ground to the underside of the base
    heel_soil: float  # soil over the heel
    front_soil: float  # soil over the toe
    front_offset: float  # the front ground below the retained ground

    @property
    def width(self) -> float:
        return self.toe + self.stem_bottom + self.heel

    @property
    def back(self) -> float:
        """x of the stem's soil face from the toe."""
        return self.toe + self.stem_bottom

    def thickness(self, y: float) -> float:
        """The stem's thickness [m] at ``y`` above the top of the base."""
        share = min(max(y / self.stem_height, 0.0), 1.0) if self.stem_height else 0.0
        return self.stem_bottom + (self.stem_top - self.stem_bottom) * share


def section_of(wall: Any, ground_level: float) -> Section:
    """The :class:`Section` of a :class:`~saengine.library.substructure.RetainingWall`."""
    mm = 1e-3
    retained = wall.retainedLevel if wall.retainedLevel is not None else ground_level
    base_top = wall.foundingLevel + wall.baseThickness
    front = wall.frontLevel if wall.frontLevel is not None else base_top
    return Section(
        toe=wall.toe * mm,
        heel=wall.heel * mm,
        stem_top=wall.stemTop * mm,
        stem_bottom=wall.stemBottom * mm,
        base=wall.baseThickness * mm,
        stem_height=(wall.topLevel - base_top) * mm,
        retained_depth=(retained - wall.foundingLevel) * mm,
        heel_soil=max(retained - base_top, 0.0) * mm,
        front_soil=max(front - base_top, 0.0) * mm,
        front_offset=(retained - max(front, wall.foundingLevel)) * mm,
    )


def midpoint(path: list[list[float]]) -> tuple[float, float]:
    """The point half way along a path [mm]."""
    lengths = [math.dist(a, b) for a, b in pairwise(path)]
    half = sum(lengths) / 2
    for (a, b), length in zip(pairwise(path), lengths, strict=True):
        if half <= length and length > 0:
            t = half / length
            return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        half -= length
    return float(path[-1][0]), float(path[-1][1])


# ─────────────────────────────────── beam actions ───────────────────────────────────


def beam_actions(
    height: float,
    load: Any,
    supports: list[float],
    base_fixed: bool = True,
    divisions: int = 120,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[float]]:
    """A vertical wall strip ``height`` m tall (y up from its base), loaded by the pressure
    ``load(y)`` [kPa = kN/m per metre run] towards the front, held at its base (fixed, or
    pinned) and propped at ``supports`` (y of the floors, m; none: a cantilever). Returns the
    stations y, the moment M(y) [kN·m/m] (positive: tension at the soil face) and shear V(y)
    [kN/m] there, and the prop reactions [kN/m] (towards the soil).

    Euler-Bernoulli elements of constant EI (the props' reactions need only relative
    stiffness), consistent loads for the linear pressure in each element; the actions are then
    taken by statics from the free top: ``M(y) = ∫ q (t - y) dt - Σ R (yi - y)``."""
    props = sorted({min(max(s, 0.0), height) for s in supports if s > 1e-9})
    ys = np.unique(np.concatenate([np.linspace(0.0, height, divisions + 1), props]))
    n = len(ys)
    k = np.zeros((2 * n, 2 * n))
    f = np.zeros(2 * n)
    q = np.array([float(load(y)) for y in ys])
    for e in range(n - 1):
        length = ys[e + 1] - ys[e]
        if length <= 0:
            continue
        a, b = q[e], q[e + 1]
        ke = (
            np.array(
                [
                    [12, 6 * length, -12, 6 * length],
                    [6 * length, 4 * length**2, -6 * length, 2 * length**2],
                    [-12, -6 * length, 12, -6 * length],
                    [6 * length, 2 * length**2, -6 * length, 4 * length**2],
                ]
            )
            / length**3
        )
        fe = np.array(
            [
                length * (7 * a + 3 * b) / 20,
                length**2 * (3 * a + 2 * b) / 60,
                length * (3 * a + 7 * b) / 20,
                -(length**2) * (2 * a + 3 * b) / 60,
            ]
        )
        dofs = [2 * e, 2 * e + 1, 2 * e + 2, 2 * e + 3]
        k[np.ix_(dofs, dofs)] += ke
        f[dofs] += fe
    held = {0} | ({1} if base_fixed or not props else set())
    prop_dofs = [2 * int(np.argmin(abs(ys - s))) for s in props]
    held |= set(prop_dofs)
    free = [d for d in range(2 * n) if d not in held]
    u = np.zeros(2 * n)
    if free:
        u[free] = np.linalg.solve(k[np.ix_(free, free)], f[free])
    reaction = k @ u - f  # the supports' forces on the strip, along the load
    props_r = [-float(reaction[d]) for d in prop_dofs]
    moments = np.zeros(n)
    shears = np.zeros(n)
    # Statics from the top: the load above each station, trapezoidal in the stations.
    for i in range(n - 2, -1, -1):
        dy = ys[i + 1] - ys[i]
        force = (q[i] + q[i + 1]) / 2 * dy
        arm = dy * (q[i] + 2 * q[i + 1]) / (3 * (q[i] + q[i + 1])) if q[i] + q[i + 1] else dy / 2
        shears[i] = shears[i + 1] + force
        moments[i] = moments[i + 1] + shears[i + 1] * dy + force * arm
        for s, r in zip(props, props_r, strict=True):
            if abs(ys[i + 1] - s) < 1e-9:
                # the prop at the station above: its reaction acts from there down
                shears[i] -= r
                moments[i] -= r * dy
    return ys, moments, shears, props_r


# ─────────────────────────────────── section design ───────────────────────────────────


@dataclass
class Strip:
    """One face of a section to be designed: its factored and service moment [kN·m/m], the
    section depth h [mm], the cover to the bars [mm], the factored shear [kN/m] and where."""

    name: str
    mu: float
    ms: float
    h: float
    cover: float
    vu: float = 0.0
    where: str = ""
    wall: bool = True  # a wall (BNBC vertical minimum) or a slab (ACI 7.6.1.1)


def _flexure_area(m: float, d: float, fc: float, fy: float) -> float | None:
    from saengine.plumbing.tanks import flexure_area

    return flexure_area(m * 1e6, d, fc, fy)


def _crack(strip: Strip, dia: float, spacing: float, fc: float, ec: float) -> float:
    """EN 1992-1-1 7.3.4 crack width [mm] under the service moment, bars at one face."""
    from saengine.plumbing.tanks import crack_width, cracked_section, fctm

    if strip.ms <= 0:
        return 0.0
    area = bar_area(dia) * 1000 / spacing
    d = strip.h - strip.cover - dia / 2
    cracked = cracked_section(strip.ms * 1e6, 0.0, strip.h, d, area, strip.cover, 0.0, STEEL_E, ec)
    if cracked is None:
        return 0.0
    return float(
        crack_width(cracked, strip.h, d, strip.cover, dia, spacing, area, fctm(fc), STEEL_E, ec)[
            "wk"
        ]
    )


def aci_crack_spacing(fy: float, cover: float) -> float:
    """ACI 318-19 Table 24.3.2: the largest spacing [mm] of deformed bars nearest a tension
    face, ``380 (280/fs) - 2.5 cc ≤ 300 (280/fs)`` with fs = 2/3 fy (24.3.2.1); cc the clear
    cover [mm]."""
    fs = 2 / 3 * fy
    return min(380 * 280 / fs - 2.5 * cover, 300 * 280 / fs)


def minimum_area(strip: Strip, fy: float, dia: float) -> float:
    """The least bars at the face [mm²/m]: BNBC 2020 Part 6 Sec 6.6.3.2 vertical wall bars
    (0.0012 for bars ≤ 16 mm of fy ≥ 420, else 0.0015, of the gross section, p969), or ACI
    318-19 7.6.1.1 for the base (a slab on soil); the whole minimum at the face designed."""
    if strip.wall:
        ratio = 0.0012 if dia <= 16 and fy >= 420 else 0.0015
    else:
        ratio = min_steel_ratio(fy)
    return ratio * 1000 * strip.h


def design_strip(
    strip: Strip,
    fc: float,
    fy: float,
    ec: float,
    crack_limit: float,
    given: Any = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The bars of one face (given, or proposed) and its checks: flexure, minimum, crack width,
    ACI spacing and shear."""
    need_at = {}

    def required(dia: float) -> float | None:
        d = strip.h - strip.cover - dia / 2
        area = _flexure_area(max(strip.mu, 0.0), d, fc, fy)
        return None if area is None else max(area, minimum_area(strip, fy, dia))

    largest = min(3 * strip.h, 450.0, aci_crack_spacing(fy, strip.cover))
    bars: tuple[float, float] | None = None
    if given is not None:
        bars = (float(given.dia), float(given.spacing))
    else:
        best: tuple[float, float, float] | None = None
        for dia in DIAS:
            need = required(dia)
            if need is None:
                continue
            for spacing in SPACINGS:
                if spacing > largest:
                    continue
                area = bar_area(dia) * 1000 / spacing
                if area < need or _crack(strip, dia, spacing, fc, ec) > crack_limit:
                    continue
                if best is None or area < best[2]:
                    best = (dia, spacing, area)
                break
        bars = (best[0], best[1]) if best else (DIAS[-1], SPACINGS[-1])
    dia, spacing = bars
    area = bar_area(dia) * 1000 / spacing
    d = strip.h - strip.cover - dia / 2
    need_at["flexure"] = _flexure_area(max(strip.mu, 0.0), d, fc, fy)
    checks: list[dict[str, Any]] = []
    name = strip.name
    if need_at["flexure"] is None:
        checks.append(
            _check(
                f"{name}: flexure",
                strip.mu,
                0.0,
                "kN·m/m",
                "1.6H",
                "the section is too thin for the moment singly reinforced; thicken it",
            )
        )
    else:
        # φMn of the bars given (ACI rectangular block, φ = 0.9: tension-controlled slabs).
        a = area * fy / (0.85 * fc * 1000)
        phi_mn = 0.9 * area * fy * (d - a / 2) / 1e6
        checks.append(
            _check(
                f"{name}: flexure",
                strip.mu,
                phi_mn,
                "kN·m/m",
                "1.6H",
                f"φMn of {dia:.0f} mm at {spacing:.0f} ({area:.0f} mm²/m), d = {d:.0f} mm "
                f"({strip.where})",
            )
        )
    least = minimum_area(strip, fy, dia)
    checks.append(
        _check(
            f"{name}: minimum bars",
            least,
            area,
            "mm²/m",
            None,
            "BNBC 2020 Part 6 Sec 6.6.3.2 (p969)" if strip.wall else "ACI 318-19 7.6.1.1",
        )
    )
    wk = _crack(strip, dia, spacing, fc, ec)
    checks.append(
        _check(
            f"{name}: crack width",
            wk,
            crack_limit,
            "mm",
            "service",
            f"EN 1992-1-1 7.3.4 under Ms = {strip.ms:.1f} kN·m/m",
        )
    )
    checks.append(
        _check(
            f"{name}: bar spacing",
            spacing,
            largest,
            "mm",
            None,
            "ACI 318-19 Table 24.3.2 (fs = 2/3 fy), 3h and 450 mm",
        )
    )
    if strip.vu > 0:
        rho = area / (1000 * d)
        phi_vc, _ = one_way_shear(rho, d, fc)
        checks.append(
            _check(
                f"{name}: shear",
                strip.vu,
                phi_vc / 1e3,
                "kN/m",
                "1.6H",
                f"ACI 318-19 Table 22.5.5.1 (c), no shear reinforcement ({strip.where})",
            )
        )
    return {
        "dia": dia,
        "spacing": spacing,
        "area": round(area, 1),
        "proposed": given is None,
    }, checks


# ──────────────────────────────────── stability ────────────────────────────────────


@dataclass
class Force:
    name: str
    v: float = 0.0  # down [kN/m]
    h: float = 0.0  # towards the front [kN/m]
    x: float = 0.0  # of v from the toe [m]
    y: float = 0.0  # of h above the underside of the base [m]
    kind: str = "D"  # D, H, L, E, U (uplift)

    @property
    def moment(self) -> float:
        """About the toe [kN·m/m], positive overturning."""
        return self.h * self.y - self.v * self.x


def _water_level(soil: Soil, drained: bool) -> float | None:
    return None if drained else soil.water_table


def wall_forces(
    wall: Any, s: Section, soil: Soil, state: str, kh: float = 0.0
) -> tuple[list[Force], dict[str, Any]]:
    """The forces on a cantilever wall per metre run (service), and the pressure's terms."""
    beta = wall.backslope
    phi_top = soil.phi(0.01) or 30.0
    delta = wall.wallFriction if wall.wallFriction is not None else 2 / 3 * phi_top
    method = wall.method
    tilt = math.radians(beta if method == "rankine" else delta)
    rise = s.heel * math.tan(math.radians(beta))
    height = s.retained_depth + rise
    column = soil if rise <= 0 else _raised(soil, rise)
    water = not wall.drained
    p = column.resultant(
        0.0,
        height,
        state,  # type: ignore[arg-type]
        beta=beta,
        delta=delta,
        method=method,
        water=water,
    )
    forces = [
        Force(
            "stem", v=CONCRETE_UNIT_WEIGHT * s.stem_top * s.stem_height, x=s.back - s.stem_top / 2
        ),
        Force(
            "stem batter",
            v=CONCRETE_UNIT_WEIGHT * (s.stem_bottom - s.stem_top) * s.stem_height / 2,
            x=s.toe + 2 / 3 * (s.stem_bottom - s.stem_top),
        ),
        Force("base", v=CONCRETE_UNIT_WEIGHT * s.width * s.base, x=s.width / 2),
    ]
    sigma = soil.sigma_v(s.heel_soil) if water else soil._sigma_v_drained(s.heel_soil)
    forces.append(Force("soil over the heel", v=sigma * s.heel, x=s.back + s.heel / 2))
    if rise > 0:
        forces.append(
            Force(
                "sloping backfill",
                v=0.5 * s.heel * rise * soil.total_unit_weight(0.01),
                x=s.back + 2 / 3 * s.heel,
            )
        )
    if s.front_soil > 0:
        front = soil.below(s.front_offset)
        forces.append(
            Force("soil over the toe", v=front.sigma_v(s.front_soil) * s.toe, x=s.toe / 2)
        )
    soil_h = p["soil"] * math.cos(tilt)
    soil_v = p["soil"] * math.sin(tilt)
    surcharge_h = p["surcharge"] * math.cos(tilt)
    surcharge_v = p["surcharge"] * math.sin(tilt)
    arm = p["arm"]
    forces.append(
        Force("earth pressure", h=soil_h + p["water"], v=soil_v, x=s.width, y=arm, kind="H")
    )
    if surcharge_h or surcharge_v:
        # The surcharge's share of the arm: a uniform K q over the height, at its middle.
        forces.append(
            Force(
                "surcharge pressure",
                h=surcharge_h,
                v=surcharge_v,
                x=s.width,
                y=height / 2,
                kind="L",
            )
        )
        # its resultant was part of p["arm"]; take it out of the earth pressure's arm
        total = p["soil"] + p["water"] + p["surcharge"]
        rest = p["soil"] + p["water"]
        if rest > 1e-9:
            forces[-2].y = (total * arm - p["surcharge"] * height / 2) / rest
    if wall.surcharge:
        forces.append(
            Force(
                "surcharge on the heel", v=wall.surcharge * s.heel, x=s.back + s.heel / 2, kind="L"
            )
        )
    # Uplift and the water in front.
    level = _water_level(soil, wall.drained)
    if level is not None and level < s.retained_depth:
        u_heel = GAMMA_W * (s.retained_depth - level)
        front_water = max(min(s.retained_depth - level, s.retained_depth - s.front_offset), 0.0)
        u_toe = GAMMA_W * front_water
        total = (u_heel + u_toe) / 2 * s.width
        if total > 0:
            x = s.width * (u_toe + 2 * u_heel) / (3 * (u_toe + u_heel))
            forces.append(Force("uplift", v=-total, x=x, kind="U"))
        if front_water > 0:
            forces.append(
                Force(
                    "water in front", h=-0.5 * GAMMA_W * front_water**2, y=front_water / 3, kind="U"
                )
            )
    terms = {
        "K": column.coefficient(height / 2, state, beta, delta, 0.0, method),  # type: ignore[arg-type]
        "state": STATES[state],
        "height": height,
        "thrust": p["total"],
        "soil": p["soil"],
        "water": p["water"],
        "surcharge": p["surcharge"],
        "delta": delta,
    }
    if kh > 0:
        inc = seismic_increment(
            soil, height, kh, yielding=state == "active", beta=beta, delta=delta
        )
        k_wall = inc["kh"]
        forces.append(Force("seismic earth pressure", h=inc["force"], y=inc["arm"], kind="E"))
        for f in list(forces):
            if f.name in ("stem", "stem batter"):
                y = s.base + (s.stem_height / 2 if f.name == "stem" else s.stem_height / 3)
                forces.append(Force(f"inertia of the {f.name}", h=k_wall * f.v, y=y, kind="E"))
            elif f.name == "base":
                forces.append(Force("inertia of the base", h=k_wall * f.v, y=s.base / 2, kind="E"))
        terms["seismic"] = inc
    return forces, terms


def _raised(soil: Soil, rise: float) -> Soil:
    """The soil column measured from a surface ``rise`` m higher (a sloping backfill at the
    heel's end): the top layer extended up."""
    layers = [
        (lay[0] + rise if i else 0.0, lay[1] + rise, *lay[2:]) for i, lay in enumerate(soil.layers)
    ]
    water = None if soil.water_table is None else soil.water_table + rise
    return Soil(layers, water, soil.surcharge, soil.k0_cohesive, soil.source, soil.profile)


def factor_of_safety(resisting: float, driving: float) -> float:
    """``resisting / driving``, at most 99 (nothing driving)."""
    return min(resisting / driving, 99.0) if driving > 1e-9 else 99.0


def base_soil(soil: Soil, s: Section, verified: float | None = None) -> tuple[float, float, str]:
    """μ, the adhesion [kPa] and a note for the soil under the base: the wall's ``verified``
    friction factor, else the code pack's fixed friction factor for every soil (no adhesion),
    else tan(r φ') and the adhesion on a clay without φ'."""
    f = _factors()
    if verified is not None:
        return verified, 0.0, f"μ = {verified:g}, verified by analysis and test (the wall's)"
    if f.frictionCoefficient is not None:
        source = code_context.table("foundations").sources.get(
            "retainingWall.frictionCoefficient", ""
        )
        return (
            f.frictionCoefficient,
            0.0,
            f"μ = {f.frictionCoefficient:g}" + (f" ({source})" if source else ""),
        )
    phi = soil.phi(s.retained_depth + 0.01)
    if phi is None:
        cu = soil.cohesion(s.retained_depth + 0.01)
        return 0.0, f.adhesion * cu, f"clay: adhesion {f.adhesion:g} cu = {f.adhesion * cu:.1f} kPa"
    mu = math.tan(math.radians(f.baseFriction * phi))
    return mu, 0.0, f"μ = tan({f.baseFriction:.2f} φ') = {mu:.2f} (φ' = {phi:.0f}°)"


def base_pressure(n: float, moment_toe: float, width: float) -> tuple[float, float, float]:
    """The linear base pressure (toe, heel) [kPa] with no tension, and the eccentricity [m],
    for a vertical force ``n`` whose moment about the toe is ``moment_toe`` (resisting
    positive)."""
    if n <= 0:
        return 0.0, 0.0, math.inf
    x = moment_toe / n
    e = width / 2 - x
    if abs(e) <= width / 6:
        return n / width * (1 + 6 * e / width), n / width * (1 - 6 * e / width), e
    if x <= 0 or x >= width:
        return math.inf, 0.0, e
    if e > 0:  # towards the toe
        return 2 * n / (3 * x), 0.0, e
    return 0.0, 2 * n / (3 * (width - x)), e


def stability(
    ctx: Context, wall: Any, s: Section, soil: Soil, x: float, y: float
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """The sliding, overturning and bearing checks of a cantilever wall (static and, when
    asked for, seismic); returns (checks, the forces and pressures, notes)."""
    f = _factors()
    notes: list[str] = []
    state = wall.state()
    forces, terms = wall_forces(wall, s, soil, state)
    mu, ca, friction = base_soil(soil, s, getattr(wall, "frictionCoefficient", None))
    passive = 0.0
    if wall.passive:
        depth = s.retained_depth - s.front_offset
        if depth > 0:
            front = soil.below(s.front_offset)
            passive = front.resultant(0.0, depth, "passive", water=not wall.drained)["soil"]
    checks: list[dict[str, Any]] = []

    def assess(items: list[Force], fs_slide: float, fs_over: float, label: str) -> dict[str, Any]:
        stabilising = [i for i in items if i.kind != "L" or i.h]  # surcharge on the heel left out
        sum_v = sum(i.v for i in stabilising)
        sum_h = sum(i.h for i in items if i.h > 0)
        resisting_h = -sum(i.h for i in items if i.h < 0)
        slide = mu * max(sum_v, 0.0) + ca * s.width + passive / f.passive + resisting_h
        over = sum(max(i.h * i.y, 0.0) for i in items) + sum(-i.v * i.x for i in items if i.v < 0)
        resist = sum(i.v * i.x for i in stabilising if i.v > 0) + sum(
            -i.h * i.y for i in items if i.h < 0
        )
        checks.append(
            _check(
                f"Sliding{label}",
                fs_slide,
                factor_of_safety(slide, sum_h),
                "FS",
                "service",
                f"{friction}; resisting {slide:.1f} / driving {sum_h:.1f} kN/m"
                + (f"; passive {passive:.1f} / {f.passive:g}" if passive else ""),
            )
        )
        checks.append(
            _check(
                f"Overturning{label}",
                fs_over,
                factor_of_safety(resist, over),
                "FS",
                "service",
                f"about the toe: resisting {resist:.1f} / overturning {over:.1f} kN·m/m",
            )
        )
        # Bearing: every vertical force, the surcharge included.
        n = sum(i.v for i in items)
        m_toe = -sum(i.moment for i in items)
        toe_p, heel_p, e = base_pressure(n, m_toe, s.width)
        return {"n": n, "toe": toe_p, "heel": heel_p, "e": e}

    static = assess(forces, f.sliding, f.overturning, "")
    seismic_pressures = None
    kh = _peak_acceleration(ctx) if wall.seismic else None
    if kh:
        k_wall = kh * (f.yieldingKh if state == "active" else 1.0)
        quake, quake_terms = wall_forces(wall, s, soil, state, k_wall)
        terms["seismic"] = quake_terms.get("seismic")
        seismic_pressures = assess(quake, f.seismic, f.seismic, " (seismic)")
    elif wall.seismic:
        notes.append(f"{wall.id}: no seismic zone coefficient Z; the seismic check is left out")
    # Bearing against qa.
    width_mm = s.width * 1e3
    bearing = ctx.soil.at(
        x, y, wall.foundingLevel, width_mm, max(wall.length(), width_mm), None, wall.id
    )
    front = soil.below(s.front_offset)
    overburden = front.sigma_v(max(s.retained_depth - s.front_offset, 0.0))
    net = static["toe"] - overburden
    if bearing.qa is not None:
        checks.append(
            _check(
                "Bearing",
                max(net, static["heel"] - overburden),
                bearing.qa,
                "kPa",
                "service",
                f"net of the overburden {overburden:.1f} kPa in front; {bearing.note}",
            )
        )
    else:
        notes.append(f"{wall.id}: bearing not checked: {bearing.note or 'no qa'}")
    checks.append(
        _check(
            "Resultant in the middle third",
            abs(static["e"]),
            s.width / 6,
            "m",
            "service",
            "no tension under the base",
            flag=True,
        )
    )
    return (
        checks,
        {
            "forces": [vars(i) for i in forces],
            "pressure": terms,
            "base": static,
            "seismicBase": seismic_pressures,
            "qa": bearing.qa,
        },
        notes,
    )


def _peak_acceleration(ctx: Context) -> float | None:
    """(2/3) Z S [g] of the project (:func:`saengine.fem.ssi.peak_acceleration`)."""
    from saengine.fem.ssi import peak_acceleration

    try:
        return peak_acceleration(ctx.settings)
    except (ValueError, KeyError, AttributeError, TypeError):  # a custom location without Z
        return None


# ────────────────────────────────────── design ──────────────────────────────────────


def _materials(ctx: Context, wall: Any) -> tuple[float, float, float, str]:
    concrete = ctx.concrete(wall.material, wall.id)
    fc = float(concrete.concrete.fc)  # type: ignore[union-attr]
    ec = 4700 * math.sqrt(fc)  # ACI 318-19 19.2.2.1 (b)
    if wall.reinforcement is None:
        fy, rebar = 420.0, ""  # proposed bars: Grade 420
    else:
        rebar_material = ctx.rebar(wall.reinforcement.material)
        fy, rebar = float(rebar_material.steel.fy), rebar_material.id  # type: ignore[union-attr]
    return fc, fy, ec, rebar


def _stem_load(soil: Soil, wall: Any, s: Section, state: str) -> Any:
    """The service pressure on the stem's soil face at y above the top of the base [kPa]
    (Rankine with the backfill slope, horizontal)."""
    top_depth = s.retained_depth - s.base  # the top of the base below the retained ground
    tilt = math.cos(math.radians(wall.backslope))

    def load(y: float) -> float:
        p = soil.pressure(top_depth - y, state, beta=wall.backslope, water=not wall.drained)  # type: ignore[arg-type]
        return (p["soil"] + p["surcharge"]) * tilt + p["water"]

    return load


def design_retaining_wall(
    ctx: Context, wall: Any, profiles: list[Any] | None = None
) -> tuple[dict[str, Any], list[str]]:
    """The checks of one retaining or basement wall (see the module's notes), in the format of
    the foundations of :func:`saengine.substructure.report.report`."""
    from saengine.substructure.piles import profiles_of

    if profiles is None:
        profiles = profiles_of(ctx.soil_text)[0]
    f = _factors()
    s = section_of(wall, ctx.ground_level)
    if s.stem_height <= 0:
        raise Skip("the top of the wall is not above its base")
    x, y = midpoint(wall.path)
    options = ctx.substructure.earthPressure
    backfill = wall.backfill.model_dump() if wall.backfill is not None else None
    soil = soil_column(
        profiles, x, y, wall.designWaterTable, wall.surcharge, options.k0Cohesive, backfill
    )
    if (
        wall.retainedLevel is not None
        and abs(wall.retainedLevel - ctx.ground_level) > 1
        and not backfill
    ):
        soil.notes.append(
            "the borehole's layers are measured down from the retained ground (not from the "
            "borehole's own ground level)"
        )
    fc, fy, ec, _ = _materials(ctx, wall)
    state = wall.state()
    notes = [f"{wall.id}: soil from {soil.source}"] + [f"{wall.id}: {n}" for n in soil.notes]
    checks: list[dict[str, Any]] = []
    detail: dict[str, Any] = {}
    bars_given = wall.reinforcement
    cover = float(bars_given.cover) if bars_given is not None else 50.0
    kh = _peak_acceleration(ctx) if wall.seismic else None

    # ── stem ──
    hs = s.stem_height
    if wall.kind == "basement":
        supports = [
            (level - (wall.foundingLevel + wall.baseThickness)) * 1e-3 for level in wall.supports
        ]
    else:
        supports = []
    service_load = _stem_load(soil, wall, s, state)
    ys, m_s, v_s, props = beam_actions(
        hs, service_load, supports, wall.baseFixed or wall.kind == "cantilever"
    )
    strength = np.array(m_s) * f.hFactor
    shear = np.array(v_s) * f.hFactor
    if kh:
        k_wall = kh * (f.yieldingKh if state == "active" else 1.0)
        inc = seismic_increment(
            soil, s.retained_depth - s.base, k_wall, yielding=state == "active", beta=wall.backslope
        )
        bottom, top = inc["bottom"], inc["top"]
        height = max(s.retained_depth - s.base, 1e-9)

        def quake(yy: float) -> float:
            return (
                bottom + (top - bottom) * min(max(yy / height, 0.0), 1.0) if yy <= height else 0.0
            )

        _, m_e, v_e, _ = beam_actions(
            hs, quake, supports, wall.baseFixed or wall.kind == "cantilever"
        )
        strength = np.maximum(strength, np.array(m_s) * f.hFactor + np.array(m_e))
        shear = np.maximum(np.abs(shear), np.abs(np.array(v_s) * f.hFactor + np.array(v_e)))
        notes.append(f"{wall.id}: {inc.get('note', '')}")
    # Faces: the soil face (positive M) and the front face (negative M).
    h_base = s.thickness(0.0) * 1e3
    back_i = int(np.argmax(strength))
    front_i = int(np.argmin(strength))
    held = [0.0] + supports
    d_m = (h_base - cover - 8) * 1e-3

    def away(yy: float) -> bool:
        return all(abs(yy - sy) >= d_m - 1e-9 for sy in held)

    v_at = max((abs(v) for yy, v in zip(ys, shear, strict=True) if away(yy)), default=0.0)
    back = Strip(
        "Stem, soil face",
        float(strength[back_i]),
        float(m_s[back_i]),
        s.thickness(ys[back_i]) * 1e3,
        cover,
        v_at,
        f"{'base' if ys[back_i] < 1e-6 else f'{ys[back_i]:.2f} m up'}; shear d from the supports",
    )
    bars, found = design_strip(
        back, fc, fy, ec, wall.crackLimit, bars_given and bars_given.stemBack
    )
    detail["stemBack"] = bars
    checks += found
    if -strength[front_i] > 1e-6:
        front = Strip(
            "Stem, inner face",
            float(-strength[front_i]),
            float(max(-m_s[front_i], 0.0)),
            s.thickness(ys[front_i]) * 1e3,
            cover,
            0.0,
            f"span, {ys[front_i]:.2f} m up",
        )
        bars, found = design_strip(
            front, fc, fy, ec, wall.crackLimit, bars_given and bars_given.stemFront
        )
        detail["stemFront"] = bars
        checks += found
    # Horizontal bars: BNBC 2020 Part 6 Sec 6.6.3.3, 0.0020 (≤ 16 mm, fy ≥ 420) else 0.0025,
    # half at each face.
    horizontal = bars_given.horizontal if bars_given is not None else None
    ratio = 0.0020 if (horizontal is None or horizontal.dia <= 16) and fy >= 420 else 0.0025
    need = ratio * 1000 * h_base / 2
    if horizontal is None:
        dia = 12.0
        spacing = next(
            (sp for sp in SPACINGS if bar_area(dia) * 1000 / sp >= need and sp <= 450), 100.0
        )
        detail["horizontal"] = {
            "dia": dia,
            "spacing": spacing,
            "area": round(bar_area(dia) * 1000 / spacing, 1),
            "proposed": True,
        }
    else:
        dia, spacing = float(horizontal.dia), float(horizontal.spacing)
        detail["horizontal"] = {
            "dia": dia,
            "spacing": spacing,
            "area": round(bar_area(dia) * 1000 / spacing, 1),
            "proposed": False,
        }
    checks.append(
        _check(
            "Stem: horizontal bars (each face)",
            need,
            detail["horizontal"]["area"],
            "mm²/m",
            None,
            f"BNBC 2020 Part 6 Sec 6.6.3.3, {ratio:.4f} of the gross section, half per face (p969)",
        )
    )
    actions = {
        "y": [round(float(v), 3) for v in ys[:: max(len(ys) // 40, 1)]],
        "M": [round(float(v), 2) for v in np.array(m_s)[:: max(len(ys) // 40, 1)]],
        "V": [round(float(v), 2) for v in np.array(v_s)[:: max(len(ys) // 40, 1)]],
        "props": [round(r, 2) for r in props],
    }

    # ── stability and base (cantilever walls) ──
    stable: dict[str, Any] = {}
    if wall.kind == "cantilever":
        found, stable, more = stability(ctx, wall, s, soil, x, y)
        checks += found
        notes += more
        checks += _base_design(wall, s, soil, state, fc, fy, ec, cover, detail, bars_given)
    else:
        u = soil.u(s.retained_depth) if not wall.drained else 0.0
        stable = {"uplift": round(u, 2)}
        if u > 0:
            notes.append(
                f"{wall.id}: uplift {u:.1f} kPa under the base at the founding level (BNBC 2020 "
                "Part 6 Sec 2.6.5.2); the flotation of the basement is checked with the raft"
            )
    governing = max((c["utilisation"] for c in checks if not c["flag"]), default=0.0)
    ok = all(c["ok"] for c in checks if not c["flag"])
    result = {
        "id": wall.id,
        "type": "retainingWall",
        "kind": wall.kind,
        "columns": [wall.wall] if wall.wall else [],
        "checks": checks,
        "utilisation": governing,
        "ok": ok,
        "sizes": {
            "width": round(s.width * 1e3),
            "toe": wall.toe,
            "heel": wall.heel,
            "stemTop": wall.stemTop,
            "stemBottom": wall.stemBottom,
            "base": wall.baseThickness,
            "height": round((s.stem_height + s.base) * 1e3),
            "length": round(wall.length()),
        },
        "pressureState": STATES[state],
        "soil": soil.source,
        "waterTable": soil.water_table,
        "bars": detail,
        "actions": actions,
        "stability": _rounded(stable),
    }
    return result, notes


def _base_design(
    wall: Any,
    s: Section,
    soil: Soil,
    state: str,
    fc: float,
    fy: float,
    ec: float,
    cover: float,
    detail: dict[str, Any],
    bars_given: Any,
) -> list[dict[str, Any]]:
    """The toe (bottom bars) and the heel (top bars) under the envelope of 1.2D + 1.6H + 1.6L
    and 0.9D + 1.6H, with the service D + H + L for the crack widths."""
    f = _factors()
    forces, _ = wall_forces(wall, s, soil, state)
    combos = {
        "1.2D + 1.6H + 1.6L": {"D": 1.2, "H": f.hFactor, "L": 1.6, "U": f.hFactor},
        "0.9D + 1.6H": {"D": 0.9, "H": f.hFactor, "L": 0.0, "U": f.hFactor},
        "service": {"D": 1.0, "H": 1.0, "L": 1.0, "U": 1.0},
    }
    xs = np.linspace(0.0, s.width, 201)
    results: dict[str, dict[str, float]] = {}
    for name, factor in combos.items():
        items = [
            Force(
                i.name,
                i.v * factor.get(i.kind, 1.0),
                i.h * factor.get(i.kind, 1.0),
                i.x,
                i.y,
                i.kind,
            )
            for i in forces
        ]
        n = sum(i.v for i in items)
        toe_p, heel_p, _ = base_pressure(n, -sum(i.moment for i in items), s.width)
        if not math.isfinite(toe_p) or not math.isfinite(heel_p):
            toe_p = heel_p = 0.0
        q = toe_p + (heel_p - toe_p) * xs / s.width
        # Downward loads on the base: its own weight, the soil and surcharge over the heel and
        # the toe, the uplift up (net of the soil pressure: q is the soil's reaction).
        dead = factor["D"]
        down = np.full_like(xs, CONCRETE_UNIT_WEIGHT * s.base * dead)
        on_heel = xs >= s.back
        on_toe = xs <= s.toe
        for i in items:
            if (
                i.name in ("soil over the heel", "sloping backfill", "surcharge on the heel")
                and s.heel
            ):
                down[on_heel] += i.v / s.heel
            elif i.name == "soil over the toe" and s.toe:
                down[on_toe] += i.v / s.toe
        uplift = next((i for i in items if i.name == "uplift"), None)
        up = np.zeros_like(xs)
        if uplift is not None:
            # linear, its resultant at uplift.x: u(x) = a + b x
            total = -uplift.v
            xbar = uplift.x
            b = (xbar - s.width / 2) * 12 * total / s.width**3
            a = total / s.width - b * s.width / 2
            up = a + b * xs
        net = q + up - down  # upward positive
        toe_m = float(_integral(np.where(on_toe, net * (s.toe - xs), 0.0), xs))
        heel_m = float(_integral(np.where(on_heel, -net * (xs - s.back), 0.0), xs))
        pv = next((i.v for i in items if i.name == "earth pressure"), 0.0)
        heel_m += pv * s.heel
        d_toe = (s.base * 1e3 - COVER_UNDER_BASE - 8) * 1e-3
        toe_v = float(_integral(np.where(xs <= max(s.toe - d_toe, 0.0), net, 0.0), xs))
        heel_v = float(_integral(np.where(on_heel, -net, 0.0), xs)) + pv
        results[name] = {"toeM": toe_m, "heelM": heel_m, "toeV": toe_v, "heelV": heel_v}
    strength = [r for k, r in results.items() if k != "service"]
    service = results["service"]
    h = s.base * 1e3
    checks: list[dict[str, Any]] = []
    toe = Strip(
        "Toe, bottom",
        max(r["toeM"] for r in strength),
        max(service["toeM"], 0.0),
        h,
        COVER_UNDER_BASE,
        max(abs(r["toeV"]) for r in strength),
        "stem's front face",
        wall=False,
    )
    bars, found = design_strip(
        toe, fc, fy, ec, wall.crackLimit, bars_given and bars_given.toeBottom
    )
    detail["toeBottom"] = bars
    checks += found
    heel = Strip(
        "Heel, top",
        max(r["heelM"] for r in strength),
        max(service["heelM"], 0.0),
        h,
        cover,
        max(abs(r["heelV"]) for r in strength),
        "stem's back face",
        wall=False,
    )
    bars, found = design_strip(heel, fc, fy, ec, wall.crackLimit, bars_given and bars_given.heelTop)
    detail["heelTop"] = bars
    checks += found
    least = min_steel_ratio(fy) * 1000 * h / 2
    given = bars_given.baseDistribution if bars_given is not None else None
    dia, spacing = (
        (float(given.dia), float(given.spacing))
        if given
        else (
            12.0,
            next(
                (
                    sp
                    for sp in SPACINGS
                    if bar_area(12.0) * 1000 / sp >= least and sp <= min(3 * h, 450)
                ),
                100.0,
            ),
        )
    )
    detail["baseDistribution"] = {
        "dia": dia,
        "spacing": spacing,
        "area": round(bar_area(dia) * 1000 / spacing, 1),
        "proposed": given is None,
    }
    checks.append(
        _check(
            "Base: distribution bars (each face)",
            least,
            detail["baseDistribution"]["area"],
            "mm²/m",
            None,
            "ACI 318-19 7.6.1.1 (shrinkage and temperature), half per face",
        )
    )
    return checks


def _integral(values: np.ndarray, xs: np.ndarray) -> float:
    """The trapezoidal integral of ``values`` over ``xs``."""
    return float(np.sum((values[1:] + values[:-1]) * np.diff(xs)) / 2)


def _rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 3) if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_rounded(v) for v in value]
    return value


# ───────────────────────────────────── flotation ─────────────────────────────────────


def flotation(ctx: Context, profiles: list[Any]) -> dict[str, Any] | None:
    """The flotation of the basement (BNBC 2020 Part 6 Sec 2.6.5.2, p680): the uplift
    ``U = γw hw A`` on each raft under the design water table against the dead load that holds
    it down: the D and SD base reactions of the analysis and the rafts' own weight,
    ``FS = k W / U ≥ flotation`` with k the pack's factor on the dead load (0.9 W ≥ U in the
    default pack). None when the substructure has no basement wall and no raft below the water
    table."""
    from saengine.library.substructure import polygon_area

    rafts = [r for r in ctx.substructure.foundations if r.type == "raft" and r.outline]
    if not rafts or not any(w.kind == "basement" for w in ctx.substructure.retainingWalls):
        return None
    options = ctx.substructure.earthPressure
    uplift = weight = 0.0
    parts = []
    for raft in rafts:
        center = np.mean(np.array(raft.outline, dtype=float), axis=0)
        soil = soil_column(profiles, float(center[0]), float(center[1]), options.designWaterTable)
        depth = (ctx.ground_level - ctx.founding_level(raft)) * 1e-3
        area = abs(polygon_area(raft.outline)) * 1e-6
        u = soil.u(depth)
        uplift += u * area
        weight += CONCRETE_UNIT_WEIGHT * area * (raft.thickness or 0.0) * 1e-3
        parts.append(f"{raft.id}: u = {u:.1f} kPa on {area:.0f} m²")
    if uplift <= 0:
        return None
    if ctx.loads is None:
        return {
            "check": None,
            "note": "; ".join(parts) + f"; flotation not checked: {ctx.no_loads}",
        }
    dead = {"D": 1.0, "SD": 1.0}
    for base in ctx.loads.bases:
        weight += -float(ctx.loads.resultant(base, dead, [0.0, 0.0, 0.0])[2]) * 1e-3
    factors = _factors()
    fs, share = factors.flotation, factors.flotationDead
    source = code_context.table("foundations").sources.get("retainingWall.flotation", "")
    check = _check(
        "Flotation of the basement",
        fs,
        factor_of_safety(share * weight, uplift),
        "FS",
        f"{share:g}D + B" if share != 1 else "D + SD",
        f"{share:g} W / U with W = {weight:.0f} kN (D + SD reactions and the rafts), U = "
        f"{uplift:.0f} kN" + (f" ({source})" if source else "") + "; " + "; ".join(parts),
    )
    return {"check": check, "note": ""}


def design_retaining_walls(ctx: Context) -> tuple[list[dict], list[dict], list[str]]:
    """Every retaining wall of the substructure: (results, skipped, notes)."""
    from saengine.substructure.piles import profiles_of

    walls = ctx.substructure.retainingWalls
    if not walls:
        return [], [], []
    profiles = profiles_of(ctx.soil_text)[0]
    results: list[dict] = []
    skipped: list[dict] = []
    notes: list[str] = []
    for wall in walls:
        try:
            result, found = design_retaining_wall(ctx, wall, profiles)
        except Skip as reason:
            skipped.append({"id": wall.id, "type": "retainingWall", "reason": str(reason)})
            continue
        except ValueError as error:
            skipped.append({"id": wall.id, "type": "retainingWall", "reason": str(error)})
            continue
        results.append(result)
        notes += found
    floats = flotation(ctx, profiles)
    if floats is not None:
        if floats["check"] is not None:
            results.append(
                {
                    "id": "Basement",
                    "type": "flotation",
                    "columns": [],
                    "checks": [floats["check"]],
                    "utilisation": floats["check"]["utilisation"],
                    "ok": floats["check"]["ok"],
                }
            )
        if floats["note"]:
            notes.append(floats["note"])
    return results, skipped, notes

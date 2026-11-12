"""Dimension and detailing rules of masonry: effective height, length and thickness,
slenderness, stiffening walls, minimum thicknesses, basement and free-standing walls, parapets,
arches and corbels, and the bar details of reinforced masonry (development, laps, bends).

Every number comes from the code pack's ``masonry`` table (``dimensions`` and
``reinforcement``); the clause of each rule is in its ``clauses``. Lengths in mm, stresses in
MPa, loads in kN/m. The wall checks (:mod:`saengine.design.masonry_asd`) use the ones that
follow from a wall pier of the model; the others serve the drawings, the templates and hand
checks.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.design import masonry as M


def _dims() -> Any:
    return M.table().dimensions


def _bars() -> Any:
    return M.table().reinforcement


# ─────────────────────────────── effective height, length, thickness ───────────────────────────────


def effective_height(clear_height: float, braced_top: bool = True) -> float:
    """h' of a wall: the clear height between the lateral supports at top and bottom; twice
    the height above the support when the top is not supported (a free top)."""
    if braced_top:
        return clear_height
    return float(_dims().effectiveHeight["unsupportedTop"]) * clear_height


def effective_height_column(height: float, supported: bool = True) -> float:
    """h' of a column in one direction: its height when laterally supported at the top in that
    direction, twice it when not."""
    return height if supported else float(_dims().effectiveHeight["columnUnsupported"]) * height


def effective_height_between_openings(
    span: float, opening: float, full_restraint: bool = True, normal: bool = True
) -> float:
    """h' of the masonry between openings (a column by definition): ``span`` the distance
    between the supports, ``opening`` the height of the taller opening; ``normal``: for the
    direction normal to the wall's plane (else parallel to it)."""
    rules = _dims().effectiveHeight
    if full_restraint:
        if not normal:
            return span
        own = rules["openingFullRestraint"]
        return float(own["spanShare"]) * span + float(own["openingShare"]) * opening
    own = rules["openingPartialRestraint"]
    if not normal:
        return float(own["inPlane"]) * span
    return span if opening <= float(own["openingLimit"]) * span else float(own["above"]) * span


#: The support conditions of Table 6.7.8 (the pack's ``effectiveLength`` keys).
LENGTH_CONDITIONS = (
    "continuousBothEnds",
    "supportedContinuous",
    "supportedBothEnds",
    "freeContinuous",
    "freeSupported",
)


def effective_length(length: float, condition: str) -> float:
    """The effective length of a wall of ``length`` by its end supports (``condition``, one of
    :data:`LENGTH_CONDITIONS`)."""
    factors = _dims().effectiveLength
    if condition not in LENGTH_CONDITIONS:
        raise ValueError(f"unknown support condition '{condition}'")
    return float(factors[condition]) * length


def opening_clear_of_cross_wall(distance: float, height: float) -> bool:
    """True when an opening ``distance`` from the cross wall's face is clear of the H/8 zone in
    which the continuous-wall factor needs no opening (``height`` H of the wall)."""
    return distance >= float(_dims().effectiveLength["openingClearShare"]) * height


def _interp(xs: list[float], ys: list[float], x: float) -> float:
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    for k in range(1, len(xs)):
        if x <= xs[k]:
            share = (x - xs[k - 1]) / (xs[k] - xs[k - 1])
            return float(ys[k - 1] + share * (ys[k] - ys[k - 1]))
    return float(ys[-1])  # pragma: no cover


def stiffening_coefficient(spacing_ratio: float, thickness_ratio: float) -> float:
    """k of a solid wall stiffened by pilasters (linear between the rows and columns, the
    table's ends outside them): ``spacing_ratio`` lp/wp (pilaster spacing / width),
    ``thickness_ratio`` tp/tw (pilaster thickness with the wall / wall thickness)."""
    s = _dims().stiffening
    by_thickness = [_interp(s.thicknessRatios, row, thickness_ratio) for row in s.k]
    return _interp(s.spacingRatios, by_thickness, spacing_ratio)


def effective_thickness_cavity(
    t1: float, t2: float, both_loaded: bool
) -> float | tuple[float, float]:
    """The effective thickness of a cavity wall: each limb's own when both are loaded (the
    pair returned), else √(t1² + t2²)."""
    if both_loaded:
        return t1, t2
    return math.hypot(t1, t2)


def slenderness_limit(member: str = "wall") -> float:
    """The largest slenderness ratio of a load-bearing wall or column."""
    return float(_dims().slenderness[member])


def slenderness_ratio(h_eff: float, t_eff: float, l_eff: float | None = None) -> float:
    """A wall's slenderness: h'/t, or the lesser of h'/t and l'/t with an effective length."""
    ratio = h_eff / t_eff
    return min(ratio, l_eff / t_eff) if l_eff is not None else ratio


def flange_width(intersected_thickness: float) -> float:
    """Largest overhanging flange of an intersecting wall on each side of a shear wall."""
    return float(_dims().flangeWidth) * intersected_thickness


def reinforced_effective_width(
    thickness: float, bar_spacing: float, bond: str = "running"
) -> float:
    """Effective width per bar in flexure of a reinforced wall: the bar spacing, at most the
    pack's multiple of the nominal thickness (running or stack bond)."""
    return min(bar_spacing, float(_dims().reinforcedWidth[bond]) * thickness)


# ─────────────────────────────── stability, minimum dimensions ───────────────────────────────


def lateral_support_force(vertical_load: float, static_reaction: float = 0.0) -> float:
    """The force a lateral support must resist: the static reaction plus the pack's share of
    the vertical load it supports."""
    return static_reaction + float(_dims().stability.lateralShare) * vertical_load


def stiffening_walls(wall_thickness: float, storeys: int) -> dict[str, float] | None:
    """Table of stiffening walls for a load-bearing wall of ``wall_thickness`` in a building of
    ``storeys`` (at most the pack's maxStoreys): ``{"storeyHeight", "thickness", "spacing"}``
    (largest storey height, least stiffening wall thickness, largest spacing), None when the
    table does not cover it (more storeys, or no stiffening wall allowed: design by analysis)."""
    st = _dims().stability
    if storeys > st.maxStoreys:
        return None
    for row in st.stiffeningWalls:
        if row.wall is None or wall_thickness <= row.wall + 1e-9:
            thickness = row.thicknessUpper if storeys >= st.upperStoreys else row.thickness
            if thickness is None:
                return None
            return {
                "storeyHeight": float(row.storeyHeight),
                "thickness": float(thickness),
                "spacing": float(row.spacing),
            }
    return None  # pragma: no cover - the last row takes any thickness


def needs_stability_analysis(length: float) -> bool:
    """A wall longer than the pack's limit needs its lateral supports checked by analysis."""
    return length > float(_dims().stability.lengthNeedingAnalysis)


def minimum_bearing_thickness(storeys: int | None, height: float, gable: float = 0.0) -> float:
    """The least nominal thickness of a load-bearing wall: the general one, or the one-storey
    stiffened wall's when the building has one storey and the wall is at most the pack's
    height (+ the gable allowance at a gable's peak, ``gable`` its height there)."""
    rule = _dims().minimumThickness
    if storeys == 1 and height - min(gable, float(rule["gable"])) <= float(rule["oneStoreyHeight"]):
        return float(rule["oneStorey"])
    return float(rule["bearing"])


def basement_ground_height(thickness: float, permanent_load: float) -> float | None:
    """The largest height of the ground above the basement floor for a basement wall of
    ``thickness`` carrying ``permanent_load`` [kN/m] by the deemed-to-satisfy table; None when
    the wall is thinner than every row (design by analysis)."""
    b = _dims().basement
    rows = [r for r in b.rows if thickness >= r.thickness - 1e-9]
    if not rows:
        return None
    row = max(rows, key=lambda r: r.thickness)
    return float(row.heavy if permanent_load > b.loadLimit else row.light)


def free_standing_ratio(pressure: float) -> float | None:
    """The largest height / thickness of a free-standing wall under the design wind pressure
    [N/m²] by the deemed-to-satisfy table (the row of the next pressure up); None above the
    table (design by the tensile stress or stability)."""
    for row in _dims().freeStanding.rows:
        if pressure <= row.pressure + 1e-9:
            return float(row.ratio)
    return None


def parapet_ok(thickness: float, height: float, wall_below: float | None = None) -> bool:
    """A parapet's least thickness, its height at most the pack's multiple of its thickness,
    and not thinner than the wall below."""
    p = _dims().parapet
    return (
        thickness >= float(p["thickness"]) - 1e-9
        and height <= float(p["heightThickness"]) * thickness + 1e-9
        and (wall_below is None or thickness >= wall_below - 1e-9)
    )


def concentrated_load_length(
    bearing: float, thickness: float, spacing: float | None = None
) -> float:
    """The wall length that may carry a concentrated load at the allowable stress: the bearing
    width plus the pack's multiple of the wall thickness, at most the loads' spacing."""
    length = bearing + float(_dims().concentratedLoadThickness) * thickness
    return min(length, spacing) if spacing is not None else length


def dispersed_width(width: float, depth: float) -> float:
    """Width of a vertical load spread down ``depth`` at the pack's angle from the vertical."""
    return width + 2.0 * depth * math.tan(math.radians(float(_dims().loadDispersion)))


def arch_thrust_ok(eccentricity: float, depth: float) -> bool:
    """The line of thrust within the middle part (the pack's share, a third) of the rib."""
    return abs(eccentricity) <= float(_dims().archThrust) * depth / 2.0 + 1e-9


def corbel_slope_ok(angle: float) -> bool:
    """A footing's or corbel's slope [° from the horizontal] at least the pack's."""
    return angle >= float(_dims().corbelSlope) - 1e-9


# ─────────────────────────────────── bar details ───────────────────────────────────


def development_length(
    db: float, fs: float, compression: bool = False, plain: bool = False
) -> float:
    """ld [mm] of a bar of diameter ``db`` at the stress ``fs`` [MPa]: tension or compression
    factor × db × fs; plain bars the pack's multiple of the tension length."""
    d = _bars().development
    if plain:
        return float(d["plainFactor"]) * float(d["tension"]) * db * fs
    return float(d["compression" if compression else "tension"]) * db * fs


def lap_length(db: float, fs: float, compression: bool = False, close: bool = False) -> float:
    """Lap length [mm]: the development length, at least the pack's diameters (compression or
    tension); with adjacent splices closer than the pack's clear spacing, increased (else
    staggered)."""
    laps = _bars().laps
    least = float(laps["compression" if compression else "tension"]) * db
    length = max(development_length(db, fs, compression), least)
    return length * (1.0 + float(laps["closeIncrease"])) if close else length


def bend_diameter(db: float, stirrup: bool = False) -> float:
    """Least inside bend diameter [mm] of a bar (Table 6.7.12 as the pack reads it); stirrups
    and ties up to the pack's small size take their own multiple."""
    r = _bars()
    if stirrup and db <= float(r.bendStirrups["smallMax"]) + 1e-9:
        return float(r.bendStirrups["small"]) * db
    for row in r.bends:
        if row.start - 1e-9 <= db <= row.to + 1e-9:
            # Overlapping rows: the larger multiple (the pack orders them so the later wins).
            best = row.diameters
            for other in r.bends:
                if other.start - 1e-9 <= db <= other.to + 1e-9:
                    best = max(best, other.diameters)
            return float(best) * db
    return float(r.bends[-1].diameters) * db


def least_clear_spacing(db: float, column: bool = False) -> float:
    """The least clear distance between parallel bars."""
    s = _bars().clearSpacing
    if column:
        return float(s["columnDiameters"]) * db
    return max(float(s["diameters"]) * db, float(s["min"]))


def least_cover(exposure: str = "interior") -> float:
    """The least cover, including the unit, by exposure ("interior", "weather", "soil")."""
    return float(_bars().cover[exposure])


def shear_spacing_limit(d: float) -> float:
    """Largest spacing of shear reinforcement: the pack's share of d, at most its maximum."""
    s = _bars().shearSpacing
    return min(float(s["depthShare"]) * d, float(s["max"]))


def column_steel_limits(area: float) -> tuple[float, float]:
    """(least, largest) vertical steel area of a reinforced masonry column of ``area``."""
    c = _bars().column
    return float(c["minRatio"]) * area, float(c["maxRatio"]) * area


__all__ = [
    "LENGTH_CONDITIONS",
    "arch_thrust_ok",
    "basement_ground_height",
    "bend_diameter",
    "column_steel_limits",
    "concentrated_load_length",
    "corbel_slope_ok",
    "development_length",
    "dispersed_width",
    "effective_height",
    "effective_height_between_openings",
    "effective_height_column",
    "effective_length",
    "effective_thickness_cavity",
    "flange_width",
    "free_standing_ratio",
    "lap_length",
    "lateral_support_force",
    "least_clear_spacing",
    "least_cover",
    "minimum_bearing_thickness",
    "needs_stability_analysis",
    "opening_clear_of_cross_wall",
    "parapet_ok",
    "reinforced_effective_width",
    "shear_spacing_limit",
    "slenderness_limit",
    "slenderness_ratio",
    "stiffening_coefficient",
    "stiffening_walls",
]

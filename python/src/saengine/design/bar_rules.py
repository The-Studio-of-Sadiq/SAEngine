"""Cover, anchorage, laps and the least and largest steel of members, by the pack's
``concreteMethods`` (``cover`` method ``exposureClass``, ``anchorage`` method ``bondStress``,
``memberSteel``).

Units: mm, MPa, N.

- Cover (:func:`nominal_cover`): cnom = cmin + Δcdev with cmin = max(cmin,b, cmin,dur, the
  pack's least); cmin,b the bar diameter (+ ``aggregateIncrease`` for aggregate above
  ``largeAggregate``); cmin,dur by the exposure class's group and the structural class: the
  pack's default class, + ``longLifeIncrease`` for a 100-year design life, - 1 when fck reaches
  the class's ``strengthReduction`` strength, - ``slabReduction`` for slabs, within S1-S6.
  Several exposure classes: the largest cover.
- Anchorage (:func:`anchorage_length`): fbd = c η1 η2 fctd (η1 1 good bond, ``eta1Poor`` else;
  η2 = (bend - φ) / 100 above ``largeBar``; fctd at most at fck ``fckCap``); lb,rqd = φ σsd /
  (4 fbd); lbd = α1 α2 lb,rqd >= lb,min, α1 = ``hookAlpha`` for bent bars with cd >
  ``hookCover`` φ, α2 = 1 - slope (cd - φ) / φ within [low, 1] for straight bars (α3-α5 = 1,
  on the safe side).
- Laps (:func:`lap_length`): l0 = α1 α2 α6 lb,rqd >= l0,min, α6 by the share of bars lapped in
  one section (the pack's steps).
- Member steel: beams and slabs (:func:`beam_rows`), columns (:func:`column_rows`), walls
  (:func:`wall_rows`), as check rows.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.design import design_strength


def _table() -> Any | None:
    pack = code_context.current()
    return pack.table("concreteMethods") if pack.has("concreteMethods") else None


def covered() -> bool:
    """True when the pack in force gives the member steel rules (and designs with partial
    factors)."""
    t = _table()
    return t is not None and t.memberSteel is not None and design_strength.partial_factors()


# ─────────────────────────────── cover ───────────────────────────────


def structural_class(
    exposure: str, fck: float, design_life: float = 50.0, slab: bool = False
) -> int:
    """The structural class (1-6) of an exposure class."""
    c = _table().cover
    s = c.structuralClass
    if design_life >= 100:
        s += c.longLifeIncrease
    reduce_at = c.strengthReduction.get(exposure)
    if reduce_at is not None and fck >= reduce_at - 1e-9:
        s -= 1
    if slab:
        s -= c.slabReduction
    return min(6, max(1, s))


def durability_cover(
    exposure: str, fck: float, design_life: float = 50.0, slab: bool = False
) -> float:
    """cmin,dur [mm] (0 for an exposure class without a cover group, e.g. XF, XA alone)."""
    c = _table().cover
    group = c.exposureGroups.get(exposure)
    if group is None:
        return 0.0
    return float(c.durability[group][structural_class(exposure, fck, design_life, slab) - 1])


def nominal_cover(
    exposures: list[str],
    bar: float,
    fck: float,
    aggregate: float | None = None,
    design_life: float = 50.0,
    slab: bool = False,
) -> dict[str, float]:
    """cnom and its parts [mm] for the bars of diameter ``bar``."""
    c = _table().cover
    cmin_b = bar + (c.aggregateIncrease if aggregate and aggregate > c.largeAggregate else 0.0)
    cmin_dur = max([durability_cover(e, fck, design_life, slab) for e in exposures] or [0.0])
    cmin = max(cmin_b, cmin_dur, c.minimum)
    return {"cminB": cmin_b, "cminDur": cmin_dur, "cmin": cmin, "cnom": cmin + c.deviation}


# ─────────────────────────────── anchorage and laps ───────────────────────────────


def bond_strength(fck: float, bar: float, good_bond: bool = True) -> float:
    """fbd [MPa]."""
    a = _table().anchorage
    u = design_strength.rules()
    eta1 = 1.0 if good_bond else a.eta1Poor
    eta2 = 1.0 if bar <= a.largeBar else (a.largeBarBend - bar) / 100
    return a.bondCoefficient * eta1 * eta2 * design_strength.fctd(min(fck, a.fckCap), u)


def basic_length(bar: float, sigma_sd: float, fck: float, good_bond: bool = True) -> float:
    """lb,rqd [mm]."""
    return bar / 4 * sigma_sd / bond_strength(fck, bar, good_bond)


def _alphas(bar: float, cd: float | None, bent: bool) -> tuple[float, float]:
    a = _table().anchorage
    alpha1 = a.hookAlpha if bent and cd is not None and cd > a.hookCover * bar else 1.0
    alpha2 = 1.0
    if not bent and cd is not None:
        alpha2 = min(1.0, max(a.coverAlphaLow, 1 - a.coverAlphaSlope * (cd - bar) / bar))
    return alpha1, alpha2


def anchorage_length(
    bar: float,
    fck: float,
    fyk: float,
    sigma_sd: float | None = None,
    good_bond: bool = True,
    compression: bool = False,
    cd: float | None = None,
    bent: bool = False,
) -> dict[str, float]:
    """lbd and its parts [mm]; σsd defaults to fyd."""
    a = _table().anchorage
    sigma = design_strength.fyd(fyk) if sigma_sd is None else sigma_sd
    lb = basic_length(bar, sigma, fck, good_bond)
    alpha1, alpha2 = (1.0, 1.0) if compression else _alphas(bar, cd, bent)
    share, n, mm = a.minCompression if compression else a.minTension
    lmin = max(share * lb, n * bar, mm)
    return {"lbrqd": lb, "alpha1": alpha1, "alpha2": alpha2, "lbmin": lmin,
            "lbd": max(alpha1 * alpha2 * lb, lmin)}  # fmt: skip


def lap_alpha6(lapped_share: float) -> float:
    a = _table().anchorage
    for share, alpha in a.lapAlpha6:
        if lapped_share <= share + 1e-9:
            return alpha
    return a.lapAlpha6[-1][1]


def lap_length(
    bar: float,
    fck: float,
    fyk: float,
    lapped_share: float = 1.0,
    sigma_sd: float | None = None,
    good_bond: bool = True,
    cd: float | None = None,
    bent: bool = False,
) -> dict[str, float]:
    """l0 and its parts [mm]."""
    a = _table().anchorage
    sigma = design_strength.fyd(fyk) if sigma_sd is None else sigma_sd
    lb = basic_length(bar, sigma, fck, good_bond)
    alpha1, alpha2 = _alphas(bar, cd, bent)
    alpha6 = lap_alpha6(lapped_share)
    share, n, mm = a.lapMin
    lmin = max(share * alpha6 * lb, n * bar, mm)
    return {"lbrqd": lb, "alpha6": alpha6, "l0min": lmin,
            "l0": max(alpha1 * alpha2 * alpha6 * lb, lmin)}  # fmt: skip


# ─────────────────────────────── member steel ───────────────────────────────


def beam_min_steel(b: float, d: float, fck: float, fyk: float) -> float:
    """As,min [mm²] of a beam or slab of width b (mean width of the tension zone)."""
    m = _table().memberSteel
    fctm = design_strength.properties(fck).fctm
    return max(m.beamMinCoefficient * fctm / fyk, m.beamMinRatio) * b * d


def column_min_steel(ned: float, area: float, fyk: float) -> float:
    m = _table().memberSteel
    return max(
        m.columnMinAxialShare * max(ned, 0.0) / design_strength.fyd(fyk), m.columnMinRatio * area
    )


def column_link_spacing(min_bar: float, least_dimension: float) -> float:
    """scl,tmax [mm] away from the beams, slabs and laps."""
    m = _table().memberSteel
    n, mm = m.linkSpacing
    return min(n * min_bar, least_dimension, mm)


def _row(
    name: str, demand: float, capacity: float, unit: str, note: str, key: str
) -> dict[str, Any]:
    from saengine.design.check import _check

    clause = code_context.cite("concreteMethods", key)
    return _check(name, demand, capacity, unit, None, note + (f" ({clause})" if clause else ""))


def beam_rows(section: Any, stirrup: Any | None = None) -> list[dict[str, Any]]:
    """Least and largest longitudinal steel of a rectangular beam, and its link spacing."""
    m = _table().memberSteel
    rows: list[dict[str, Any]] = []
    b, h, fck, fyk = section.width, section.depth, section.fc, section.fy
    for top, face in ((False, "bottom"), (True, "top")):
        bars = [x for x in section.bars if (x.y > 0 if top else x.y < 0)]
        if not bars:
            continue
        d = section.effective_depth(top=top)
        a_min = beam_min_steel(b, d, fck, fyk)
        provided = sum(x.area for x in bars)
        rows.append(
            _row(
                f"Least tension steel, {face}",
                a_min,
                provided,
                "mm²",
                f"As,min = max({m.beamMinCoefficient:g} fctm/fyk, {m.beamMinRatio:g}) b d",
                "beamSteel",
            )
        )
    rows.append(
        _row(
            "Largest steel",
            section.steel_area,
            m.beamMaxRatio * b * h,
            "mm²",
            f"As,max = {m.beamMaxRatio:g} Ac",
            "beamSteel",
        )
    )
    if stirrup is not None and getattr(stirrup, "spacing", None):
        from saengine.design import strut_shear
        from saengine.design.rc import DesignError

        try:
            d = section.effective_depth(top=False)
        except DesignError:
            d = 0.9 * h
        r = strut_shear.rules()
        if r is not None:
            rows.append(
                _row(
                    "Link spacing",
                    stirrup.spacing,
                    strut_shear.max_link_spacing(d, r),
                    "mm",
                    f"sl,max = {r.spacingShare:g} d",
                    "shearSpacing",
                )
            )
    return rows


def column_rows(
    section: Any, ned_max: float, transverse: Any | None = None
) -> list[dict[str, Any]]:
    """Least and largest steel, bar and link sizes and link spacing of a column."""
    m = _table().memberSteel
    rows: list[dict[str, Any]] = []
    area = section.gross_area
    dias = sorted({round(2 * math.sqrt(x.area / math.pi), 1) for x in section.bars})
    if not dias:
        return rows
    rows.append(
        _row(
            "Least column steel",
            column_min_steel(ned_max, area, section.fy),
            section.steel_area,
            "mm²",
            f"As,min = max({m.columnMinAxialShare:g} NEd/fyd, {m.columnMinRatio:g} Ac), "
            f"NEd = {ned_max / 1e3:.0f} kN",
            "columnSteel",
        )
    )
    rows.append(
        _row(
            "Largest column steel",
            section.steel_area,
            m.columnMaxRatio * area,
            "mm²",
            f"As,max = {m.columnMaxRatio:g} Ac outside laps ({m.columnMaxRatioLaps:g} at laps)",
            "columnSteel",
        )
    )
    rows.append(
        _row("Least column bar", m.columnMinDia, dias[0], "mm", "φ at least", "columnSteel")
    )
    if transverse is not None and getattr(transverse, "dia", None):
        need = max(m.linkMinDia, m.linkDiaShare * dias[-1])
        rows.append(
            _row(
                "Column link diameter",
                need,
                transverse.dia,
                "mm",
                f"max({m.linkMinDia:g}, {m.linkDiaShare:g} φmax)",
                "columnLinks",
            )
        )
        if getattr(transverse, "spacing", None):
            least = min(section.width, section.depth)
            rows.append(
                _row(
                    "Column link spacing",
                    transverse.spacing,
                    column_link_spacing(dias[0], least),
                    "mm",
                    f"scl,tmax = min({m.linkSpacing[0]:g} φmin, b, {m.linkSpacing[1]:g}); "
                    f"× {m.linkSpacingReduction:g} near beams, slabs and laps (not checked here)",
                    "columnLinks",
                )
            )
    return rows


def wall_rows(thickness: float, length: float, vertical: float, horizontal: float,
              vertical_spacing: float | None = None,
              horizontal_spacing: float | None = None) -> list[dict[str, Any]]:  # fmt: skip
    """Least and largest steel of a wall [mm² over its length], with the spacings."""
    m = _table().memberSteel
    area = thickness * length
    rows = [
        _row("Least vertical steel", m.wallVerticalMin * area, vertical, "mm²",
             f"As,vmin = {m.wallVerticalMin:g} Ac", "wallSteel"),
        _row("Largest vertical steel", vertical, m.wallVerticalMax * area, "mm²",
             f"As,vmax = {m.wallVerticalMax:g} Ac", "wallSteel"),
        _row("Least horizontal steel",
             max(m.wallHorizontalShare * vertical, m.wallHorizontalMin * area), horizontal,
             "mm²", f"max({m.wallHorizontalShare:g} As,v, {m.wallHorizontalMin:g} Ac)",
             "wallSteel"),
    ]  # fmt: skip
    n, mm = m.wallVerticalSpacing
    if vertical_spacing:
        rows.append(_row("Vertical bar spacing", vertical_spacing, min(n * thickness, mm), "mm",
                         f"min({n:g} t, {mm:g})", "wallSteel"))  # fmt: skip
    if horizontal_spacing:
        rows.append(_row("Horizontal bar spacing", horizontal_spacing, m.wallHorizontalSpacing,
                         "mm", f"at most {m.wallHorizontalSpacing:g}", "wallSteel"))  # fmt: skip
    return rows

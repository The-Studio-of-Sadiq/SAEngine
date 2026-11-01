"""Time-dependent properties of concrete: creep, shrinkage and the modulus at an age (B25).

Generic methods, chosen by id in the code pack's ``concreteTime`` table; no code values live
here. The default pack (BNBC 2020 Part 6 Sec 5.13.3-5.13.4) uses:

- creep ``tabulatedCoefficient``: the final creep coefficient ``cc`` tabulated by effective
  section thickness, ambient relative humidity and age at loading (a digitised figure),
  interpolated linearly in thickness and humidity and on a log scale in the age at loading,
  clamped to the table's range; the share of the final creep reached after ``t`` days under load
  interpolated through the pack's ``development`` points (and zero at loading) on
  ``log(1 + t)``. The creep strain is ``εcc = stress / Et × cc`` (Eq 6.5.3 form);
- shrinkage ``tabulatedStrain``: the free strain tabulated by thickness and humidity at a few
  drying times, interpolated the same way in thickness and humidity and on ``log(1 + t)``
  in time from zero at the start of drying; proportional to the water content within the
  pack's range; of a symmetrically reinforced section ``ε / (1 + K ρ)`` (Eq 6.5.4 form);
- strength gain ``hyperbolic``: ``f'c(t) = t / (a + b t) f'c`` (at most f'c), and ``Et`` from the
  concrete pack's Ec rule (:func:`saengine.design.rc_detailing.concrete_modulus`) at that
  strength, as a ratio to the 28-day modulus.

Units: mm, MPa, days; strains dimensionless.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np


class NotCovered(ValueError):
    """The code pack in force has no time-dependent concrete data or no method by that id."""


def table() -> Any | None:
    """The code pack's ``concreteTime`` table; None when the pack in force has none."""
    from saengine.codes import context as code_context

    pack = code_context.current()
    return pack.table("concreteTime") if pack.has("concreteTime") else None


def required_table() -> Any:
    found = table()
    if found is None:
        raise NotCovered("the code pack in force does not cover creep and shrinkage")
    return found


def clause(key: str) -> str:
    """The pack's clause of ``key`` (its ``sources``), for the results and the report."""
    found = table()
    if found is None:
        return ""
    return found.sources.get(key) or found.source


# ─────────────────────────────────────── interpolation ───────────────────────────────────────


def _interp(x: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    """Linear, clamped to the ends."""
    return float(np.interp(x, np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)))


def _log_interp(x: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    """Linear in log(x), clamped to the ends (xs > 0)."""
    x = min(max(x, xs[0]), xs[-1])
    return _interp(math.log(x), [math.log(v) for v in xs], ys)


def _development(days: float, points: Sequence[Any]) -> float:
    """Share reached after ``days``: zero at 0, through the points on log(1 + t), 1 beyond the
    last point when it is the final value, else the last share."""
    if days <= 0:
        return 0.0
    xs = [0.0] + [math.log1p(p.days) for p in points]
    ys = [0.0] + [p.share for p in points]
    return _interp(math.log1p(days), xs, ys)


def effective_thickness(area: float, perimeter: float, sealed: bool = False) -> float:
    """Effective section thickness [mm]: 2 × area / exposed perimeter (mm², mm); the pack's
    sealed thickness when the member cannot dry."""
    if sealed:
        return float(required_table().creep.sealedThickness)
    return 2.0 * area / perimeter if perimeter > 0 else float("inf")


# ─────────────────────────────────────────── creep ───────────────────────────────────────────


def _creep_tabulated(model: Any, thickness: float, humidity: float, age: float) -> float:
    def at_thickness(key: str) -> float:
        rows = model.coefficients[key]
        ages = model.agesAtLoading
        values = [_interp(humidity, model.relativeHumidity, rows[_key(a)]) for a in ages]
        return _log_interp(max(age, 1e-9), ages, values) if len(ages) > 1 else values[0]

    keys = [_key(t) for t in model.thicknesses]
    values = [at_thickness(k) for k in keys]
    return _interp(thickness, model.thicknesses, values)


def _key(value: float) -> str:
    return f"{value:g}"


_CREEP_METHODS = {"tabulatedCoefficient": _creep_tabulated}


def creep_coefficient(thickness: float, humidity: float, age: float) -> float:
    """Final creep coefficient of concrete of effective ``thickness`` [mm] at ambient
    ``humidity`` [%] loaded at ``age`` [days], by the pack's creep method."""
    model = required_table().creep
    method = _CREEP_METHODS.get(model.method)
    if method is None:
        raise NotCovered(f"no creep method '{model.method}' in this version")
    return max(method(model, thickness, humidity, age), 0.0)


def creep_share(days: float) -> float:
    """Share of the final creep reached after ``days`` under load."""
    return _development(days, required_table().creep.development)


def creep_strain(stress: float, modulus_at_loading: float, coefficient: float) -> float:
    """Creep strain of a sustained ``stress`` (Eq 6.5.3 form): stress / Et × cc (MPa, MPa)."""
    return stress / modulus_at_loading * coefficient


def final_age() -> float:
    """Days under load the final creep coefficient is for."""
    return float(required_table().creep.finalAgeDays)


# ───────────────────────────────────────── shrinkage ─────────────────────────────────────────


def _shrinkage_tabulated(model: Any, thickness: float, humidity: float, days: float) -> float:
    if days <= 0:
        return 0.0
    keys = [_key(t) for t in model.thicknesses]
    at_points = []
    for point in model.points:
        values = [_interp(humidity, model.relativeHumidity, point.strains[k]) for k in keys]
        at_points.append(_interp(thickness, model.thicknesses, values) * model.strainUnit)
    xs = [0.0] + [math.log1p(p.days) for p in model.points]
    return _interp(math.log1p(days), xs, [0.0, *at_points])


_SHRINKAGE_METHODS = {"tabulatedStrain": _shrinkage_tabulated}


def shrinkage_strain(
    thickness: float, humidity: float, days: float, water: float | None = None
) -> float:
    """Free drying shrinkage of plain concrete (positive: shortening; negative: swelling) after
    ``days`` of drying, of effective ``thickness`` [mm] at ``humidity`` [%], for a water content
    ``water`` [litre/m³] (None: the table's reference)."""
    model = required_table().shrinkage
    method = _SHRINKAGE_METHODS.get(model.method)
    if method is None:
        raise NotCovered(f"no shrinkage method '{model.method}' in this version")
    strain = method(model, thickness, humidity, days)
    if water is not None:
        low, high = model.waterRange
        strain *= min(max(water, low), high) / model.referenceWater
    return strain


def reinforced_shrinkage(strain: float, steel_ratio: float, exposure: str) -> float:
    """Shrinkage of a symmetrically reinforced section: ε / (1 + K ρ), K of the ``exposure``
    (the pack's reinforcement coefficient key, e.g. internal or external)."""
    model = required_table().shrinkage
    k = model.reinforcementCoefficient.get(exposure)
    if k is None:
        raise NotCovered(f"the code pack gives no reinforcement coefficient for '{exposure}'")
    return strain / (1.0 + k * max(steel_ratio, 0.0))


# ───────────────────────────────────── strength and modulus ─────────────────────────────────────


def strength_share(age: float) -> float:
    """f'c(t) / f'c at ``age`` [days] by the pack's strength gain, at most 1."""
    gain = required_table().strengthGain
    if gain.method != "hyperbolic":
        raise NotCovered(f"no strength gain method '{gain.method}' in this version")
    if age <= 0:
        return 0.0
    return min(age / (gain.a + gain.b * age), 1.0)


def modulus_ratio(age: float, fc: float = 28.0, density: float | None = None) -> float:
    """E(t) / E28 by the concrete pack's Ec rule at the strength reached at ``age``."""
    from saengine.design.rc_detailing import concrete_modulus

    share = strength_share(age)
    if share <= 0:
        return 0.0
    e28 = concrete_modulus(fc, density)[0]
    return concrete_modulus(fc * share, density)[0] / e28 if e28 > 0 else 1.0


# ───────────────────────────────────── a project's conditions ─────────────────────────────────────


@dataclass(frozen=True)
class Conditions:
    """Ambient conditions and mix of a project: relative humidity [%], the reinforcement
    coefficient key, the water content [litre/m³] (None: the table's) and the days of curing
    before drying starts."""

    humidity: float
    exposure: str
    water: float | None = None
    curing: float = 7.0

    @classmethod
    def of(cls, options: Any) -> Conditions:
        """From Analysis > Creep, shrinkage and column shortening of the project settings (an
        exposure of the pack, the humidity entered or the exposure's)."""
        exposure = required_table().exposure
        chosen = getattr(exposure, getattr(options, "exposure", "indoor") or "indoor")
        humidity = getattr(options, "relativeHumidity", None) or chosen.relativeHumidity
        return cls(
            humidity=float(humidity),
            exposure=chosen.reinforcement,
            water=getattr(options, "waterContent", None),
            curing=float(getattr(options, "curingDays", 7.0)),
        )

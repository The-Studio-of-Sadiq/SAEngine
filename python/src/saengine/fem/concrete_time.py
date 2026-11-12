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

Alpha 9 P2 adds the models in time that other packs choose by their ids (the formulas are the
methods; their coefficients are the pack's), read through :func:`creep_phi`,
:func:`free_shrinkage`, :func:`creep_basis` and :func:`ageing`:

- creep ``aci209`` (ACI 209R-92): φ(t, t0) = (t - t0)^ψ / (d + (t - t0)^ψ) φu with the
  loading age, humidity and volume-to-surface factors; relative to E at loading;
- creep ``en1992AnnexB`` (EN 1992-1-1 Annex B): φ0 βc(t, t0) with φRH, β(fcm), β(t0) (t0
  adjusted for the cement), βH; relative to the 28-day tangent modulus;
- creep ``fibMC2010`` (fib Model Code 2010): basic plus drying creep; relative to Eci;
- shrinkage ``aci209``: (t - tc)^α / (f + (t - tc)^α) εshu with the curing, humidity and V/S
  factors; ``en1992AnnexB``: drying (βds kh εcd,0) plus autogenous; ``fibMC2010``: basic plus
  drying;
- strength gain ``exponential``: exp(s (1 - √(28 / t))).

Ages are from casting; drying starts at the end of curing. The parametric models need the
concrete's strength, which the analysis takes from the 28-day modulus by the pack's Ec rule
or from the project.

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
    """Days under load the final creep coefficient is for (infinite for a model in time)."""
    return float(getattr(required_table().creep, "finalAgeDays", math.inf))


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
    if age <= 0:
        return 0.0
    if gain.method == "hyperbolic":
        return min(age / (gain.a + gain.b * age), 1.0)
    if gain.method == "exponential":
        share = math.exp(gain.s * (1.0 - math.sqrt(28.0 / age)))
        return min(share, 1.0) if gain.capAt28 else share
    raise NotCovered(f"no strength gain method '{gain.method}' in this version")


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


# ───────────────────────────── alpha 9 P2: models in time, by method id ─────────────────────────────

#: χ of the age-adjusted effective modulus when the pack gives none: the usual value for
#: loads applied at once (Bažant 1972), SAEngine's generic default (stated in the results).
GENERIC_AGEING = 0.8

#: The analysis method of the shortening when the pack names none (the B25 method).
GENERIC_ANALYSIS = "superposition"

#: Display names of the method ids (the results and the report).
METHOD_NAMES = {
    "tabulatedCoefficient": "the code pack's tabulated creep coefficient",
    "tabulatedStrain": "the code pack's tabulated shrinkage",
    "aci209": "the ACI 209R-92 model",
    "en1992AnnexB": "the EN 1992-1-1 Annex B model",
    "fibMC2010": "the fib Model Code 2010 model",
}


def creep_method() -> str:
    return str(required_table().creep.method)


def shrinkage_method() -> str:
    return str(required_table().shrinkage.method)


def model_name() -> str:
    """The pack's creep and shrinkage models in words, for the results and the report."""
    creep, shrink = creep_method(), shrinkage_method()
    first, second = METHOD_NAMES.get(creep, creep), METHOD_NAMES.get(shrink, shrink)
    if first == second:
        return f"creep and shrinkage by {first}"
    return f"creep by {first}, shrinkage by {second}"


def _adjusted_age(age: float, model: Any) -> float:
    """t0 adjusted for the cement class (EN 1992-1-1 Eq B.9, fib MC2010 Eq 5.1-73), at least
    0.5 day."""
    alpha = float(model.cementExponent.get(model.cementClass, 0.0))
    return max(age * (9.0 / (2.0 + age**1.2) + 1.0) ** alpha, 0.5)


def _phi_aci209(model: Any, thickness: float, humidity: float, age: float, days: float) -> float:
    if days <= 0:
        return 0.0
    h = max(humidity, float(model.humidityMin)) / 100.0
    gamma_la = model.loadingAge[0] * max(age, 1.0) ** model.loadingAge[1]
    gamma_h = model.humidity[0] - model.humidity[1] * h
    a, b, c = model.volumeSurface
    gamma_vs = a * (1.0 + b * math.exp(-c * thickness / 2.0))  # V/S = A / u = h0 / 2 [mm]
    ultimate = model.ultimate * gamma_la * gamma_h * gamma_vs * model.otherFactor
    power = days**model.timeExponent
    return ultimate * power / (model.timeConstant + power)


def _phi_en1992(
    model: Any, thickness: float, humidity: float, age: float, days: float, fck: float
) -> float:
    if days <= 0:
        return 0.0
    fcm = fck + model.fcmMargin
    rh = min(max(humidity, 0.0), 100.0)
    a1, a2, a3 = (35.0 / fcm) ** 0.7, (35.0 / fcm) ** 0.2, (35.0 / fcm) ** 0.5
    base = (1.0 - rh / 100.0) / (0.1 * thickness ** (1.0 / 3.0))
    phi_rh = 1.0 + base if fcm <= 35.0 else (1.0 + base * a1) * a2
    beta_fcm = 16.8 / math.sqrt(fcm)
    beta_t0 = 1.0 / (0.1 + _adjusted_age(age, model) ** 0.20)
    strong = 1.0 if fcm <= 35.0 else a3
    beta_h = min(1.5 * (1.0 + (0.012 * rh) ** 18) * thickness + 250.0 * strong, 1500.0 * strong)
    beta_c = (days / (beta_h + days)) ** 0.3
    return phi_rh * beta_fcm * beta_t0 * beta_c


def _phi_fib2010(
    model: Any, thickness: float, humidity: float, age: float, days: float, fck: float
) -> float:
    if days <= 0:
        return 0.0
    fcm = fck + model.fcmMargin
    rh = min(max(humidity, 0.0), 100.0)
    t0 = _adjusted_age(age, model)
    basic = 1.8 / fcm**0.7 * math.log((30.0 / t0 + 0.035) ** 2 * days + 1.0)
    alpha_fcm = (35.0 / fcm) ** 0.5
    beta_h = min(1.5 * thickness + 250.0 * alpha_fcm, 1500.0 * alpha_fcm)
    gamma = 1.0 / (2.3 + 3.5 / math.sqrt(t0))
    drying = (
        412.0
        / fcm**1.4
        * (1.0 - rh / 100.0)
        / (0.1 * thickness / 100.0) ** (1.0 / 3.0)
        / (0.1 + t0**0.2)
        * (days / (beta_h + days)) ** gamma
    )
    return basic + drying


def creep_phi(
    thickness: float, humidity: float, age: float, days: float, fck: float = 28.0
) -> float:
    """φ(t, t0) of concrete of effective ``thickness`` [mm] at ``humidity`` [%], loaded at
    ``age`` [days after casting], ``days`` under load, of strength ``fck`` [MPa], by the pack's
    creep method (``tabulatedCoefficient``: the final value times its development). Relative
    to the modulus of :func:`creep_basis`."""
    model = required_table().creep
    if model.method == "tabulatedCoefficient":
        return creep_coefficient(thickness, humidity, age) * creep_share(days)
    if model.method == "aci209":
        return max(_phi_aci209(model, thickness, humidity, age, days), 0.0)
    if model.method == "en1992AnnexB":
        return max(_phi_en1992(model, thickness, humidity, age, days, fck), 0.0)
    if model.method == "fibMC2010":
        return max(_phi_fib2010(model, thickness, humidity, age, days, fck), 0.0)
    raise NotCovered(f"no creep method '{model.method}' in this version")


def creep_basis() -> tuple[str, float]:
    """What the creep coefficient is relative to: ``("loading", 1)`` the modulus at the age of
    loading (the Eq 6.5.3 form, ACI 209R-92), or ``("28", k)`` k × the 28-day modulus of the
    pack's Ec rule (the tangent modulus: EN 1992-1-1 3.1.4(2), fib MC2010 Eci)."""
    model = required_table().creep
    if model.method in ("en1992AnnexB", "fibMC2010"):
        return "28", float(model.tangentFactor)
    return "loading", 1.0


def _shrinkage_aci209(
    model: Any, thickness: float, humidity: float, drying: float, cured: float
) -> float:
    if drying <= 0:
        return 0.0
    curing = sorted(model.curing)
    gamma_cp = _interp(cured, [c[0] for c in curing], [c[1] for c in curing])
    rh = max(humidity, float(model.humidityMin))
    band = next((b for b in model.humidity if rh <= b[0]), model.humidity[-1])
    gamma_h = band[1] - band[2] * rh / 100.0
    gamma_vs = model.volumeSurface[0] * math.exp(-model.volumeSurface[1] * thickness / 2.0)
    ultimate = model.ultimate * gamma_cp * gamma_h * gamma_vs * model.otherFactor
    power = drying**model.timeExponent
    return ultimate * power / (model.timeConstant + power)


def _shrinkage_en1992(
    model: Any, thickness: float, humidity: float, age: float, drying: float, fck: float
) -> float:
    fcm = fck + model.fcmMargin
    rh = min(max(humidity, 0.0), 100.0)
    beta_rh = 1.55 * (1.0 - (rh / 100.0) ** 3)
    a1 = float(model.alphaDs1[model.cementClass])
    a2 = float(model.alphaDs2[model.cementClass])
    cd0 = 0.85 * ((220.0 + 110.0 * a1) * math.exp(-a2 * fcm / 10.0)) * 1e-6 * beta_rh
    kh = sorted(model.kh)
    k = _interp(thickness, [v[0] for v in kh], [v[1] for v in kh])
    cd = 0.0
    if drying > 0:
        cd = drying / (drying + 0.04 * math.sqrt(thickness**3)) * k * cd0
    ca = 0.0
    if model.autogenous and age > 0:
        ca = (1.0 - math.exp(-0.2 * math.sqrt(age))) * 2.5 * max(fck - 10.0, 0.0) * 1e-6
    return cd + ca


def _shrinkage_fib2010(
    model: Any, thickness: float, humidity: float, age: float, drying: float, fck: float
) -> float:
    fcm = fck + model.fcmMargin
    cls = model.cementClass
    basic = 0.0
    if age > 0:
        basic = (
            float(model.alphaBs[cls])
            * ((0.1 * fcm) / (6.0 + 0.1 * fcm)) ** 2.5
            * 1e-6
            * (1.0 - math.exp(-0.2 * math.sqrt(age)))
        )
    dry = 0.0
    if drying > 0:
        a1, a2 = float(model.alphaDs1[cls]), float(model.alphaDs2[cls])
        cds0 = (220.0 + 110.0 * a1) * math.exp(-a2 * fcm) * 1e-6
        beta_s1 = min((35.0 / fcm) ** 0.1, 1.0)
        rh = min(max(humidity, 0.0), 100.0)
        beta_rh = 1.55 * (1.0 - (rh / 100.0) ** 3) if rh < 99.0 * beta_s1 else -0.25
        beta_ds = (drying / (0.035 * thickness**2 + drying)) ** 0.5
        dry = cds0 * beta_rh * beta_ds
    return basic + dry


def free_shrinkage(
    thickness: float,
    humidity: float,
    age: float,
    curing: float,
    fck: float = 28.0,
    water: float | None = None,
) -> float:
    """Free shrinkage of plain concrete (shortening positive) at ``age`` [days after casting],
    drying from the end of ``curing`` [days], by the pack's shrinkage method
    (``tabulatedStrain``: :func:`shrinkage_strain` of the days of drying)."""
    model = required_table().shrinkage
    drying = age - curing
    if model.method == "tabulatedStrain":
        return shrinkage_strain(thickness, humidity, drying, water)
    if model.method == "aci209":
        return _shrinkage_aci209(model, thickness, humidity, drying, curing)
    if model.method == "en1992AnnexB":
        return _shrinkage_en1992(model, thickness, humidity, age, drying, fck)
    if model.method == "fibMC2010":
        return _shrinkage_fib2010(model, thickness, humidity, age, drying, fck)
    raise NotCovered(f"no shrinkage method '{model.method}' in this version")


def has_reinforced_shrinkage() -> bool:
    """Whether the pack's shrinkage gives the reinforced-section factor K (ε / (1 + K ρ))."""
    return bool(getattr(required_table().shrinkage, "reinforcementCoefficient", None))


def ageing() -> tuple[float, bool]:
    """(χ, given): the pack's ageing coefficient, or :data:`GENERIC_AGEING` (given False)."""
    found = getattr(required_table(), "ageing", None)
    if found is None:
        return GENERIC_AGEING, False
    return float(found.chi), True


def analysis_method(chosen: str | None = None) -> str:
    """The shortening's analysis method: the project's choice (``chosen``, unless "pack"),
    else the pack's, else :data:`GENERIC_ANALYSIS`."""
    if chosen and chosen != "pack":
        return chosen
    found = getattr(required_table(), "analysis", None)
    return str(found.method) if found is not None else GENERIC_ANALYSIS


def strength_from_modulus(modulus: float) -> float:
    """The concrete strength [MPa] whose modulus by the pack's Ec rule is ``modulus`` [MPa]
    (the rule goes with √f'c), clamped to 12-100 MPa."""
    from saengine.design.rc_detailing import concrete_modulus

    unit = concrete_modulus(1.0)[0]
    if unit <= 0 or modulus <= 0:
        return 28.0
    return min(max((modulus / unit) ** 2, 12.0), 100.0)

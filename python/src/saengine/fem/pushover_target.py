"""The target displacement of a pushover, by the method the code pack names.

The code pack's ``pushover`` table (:class:`saengine.codes.tables.PushoverTable`) says how far a
pushover must go and how its target displacement is found. One method is implemented:

``coefficient`` (the displacement coefficient method):

1. a bilinear curve is fitted to the capacity curve: its first segment meets the curve at
   ``bilinearFitShare`` × the effective yield strength Vy, its second meets it at the target
   displacement δt, and the areas under the two curves up to δt are equal;
2. the effective period Te = T1·√((V1/δ1) / (Vy/δy)), with T1, V1 and δ1 of the first increment
   of lateral load;
3. δt = C0·C1·Sa(Te)·(Te/2π)²·g, Sa from the code's spectrum with the pack's R and I (the real,
   unreduced spectrum), C0 = Σwᵢφᵢ / Σwᵢφᵢ² over the levels, C1 = 1 where Te exceeds the pack's
   corner period, else [1 + (Rd - 1)·Ts/Te] / Rd with Rd = Sa / (Vy/W).

δt depends on the fit and the fit on δt, so the two are iterated until δt settles.

The capacity curve is checked as well: it must reach ``pushToTarget`` × δt, and the base shear
may not drop in any step up to ``noDropToTarget`` × δt.

The first increment's values come from the run itself: δ1 and V1 of its first step, the shape
φ of the displacements of the masses in that step (normalised to 1 at the control point), and
T1 from the Rayleigh quotient of that step (2π·√(Σmᵢuᵢ² / ΣFᵢuᵢ)), which is the fundamental
period exactly when the load pattern is the fundamental mode's.

Units: m, N, s; Sa in g.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np

#: Acceleration due to gravity [m/s²].
G = 9.80665
#: Fewer steps than this to the target displacement: the curve is too coarse (a note).
MIN_STEPS_TO_TARGET = 5


def table() -> Any | None:
    """The code pack's ``pushover`` table; None when the pack in force has none."""
    from saengine.codes import context as code_context

    pack = code_context.current()
    return pack.table("pushover") if pack.has("pushover") else None


def clause(key: str) -> str:
    """The pack's clause of ``key`` (its ``sources``), for the results and the report."""
    found = table()
    if found is None:
        return ""
    return found.sources.get(key) or found.source


# ───────────────────────────────────── the curve ─────────────────────────────────────


def _upto(d: np.ndarray, v: np.ndarray, at: float) -> tuple[np.ndarray, np.ndarray]:
    """The curve from its start to displacement ``at`` (interpolated there)."""
    inside = d < at
    dd, vv = d[inside], v[inside]
    return np.append(dd, at), np.append(vv, float(np.interp(at, d, v)))


def _first_reaching(d: np.ndarray, v: np.ndarray, force: float) -> float | None:
    """The displacement at which the curve first reaches ``force`` (interpolated)."""
    for k in range(1, len(d)):
        if v[k] >= force:
            if v[k] == v[k - 1]:
                return float(d[k])
            t = (force - v[k - 1]) / (v[k] - v[k - 1])
            return float(d[k - 1] + t * (d[k] - d[k - 1]))
    return None


def bilinear_fit(
    displacement: Any, shear: Any, target: float, share: float = 0.6
) -> dict[str, float]:
    """The bilinear curve of the capacity curve (``displacement``, ``shear`` from the origin)
    up to ``target``: the first segment through the curve at ``share``·Vy, the second through
    the curve at ``target``, equal areas. Returns ``{"Vy", "dy", "Ke", "Vt", "target",
    "elastic"}`` (``elastic``: the curve is straight to the target, Vy = Vt)."""
    d, v = np.asarray(displacement, dtype=float), np.asarray(shear, dtype=float)
    d, v = _upto(d, v, target)
    vt = float(v[-1])
    area = float(np.trapezoid(v, d))
    vy = float(v.max())
    ke = vy / target if target > 0 else 0.0
    elastic = False
    for _ in range(200):
        reach = _first_reaching(d, v, share * vy)
        if reach is None or reach <= 0:
            elastic = True
            break
        ke = share * vy / reach
        denominator = target - vt / ke
        numerator = 2 * area - vt * target
        if denominator <= 1e-12 * target or numerator <= 1e-9 * vt * target:
            elastic = True
            break
        new = numerator / denominator
        if abs(new - vy) <= 1e-9 * max(vy, 1.0):
            vy = new
            break
        vy = new
    dy = vy / ke if ke > 0 else target
    if elastic or dy >= target:
        vy, dy = vt, target
        ke = vt / target if target > 0 else 0.0
        elastic = True
    return {"Vy": vy, "dy": dy, "Ke": ke, "Vt": vt, "target": target, "elastic": elastic}


def c0_factor(weights: Any, shape: Any) -> float:
    """C0 = Σwᵢφᵢ / Σwᵢφᵢ² of the level weights and the shape vector (φ = 1 at the control
    point)."""
    w, phi = np.asarray(weights, dtype=float), np.asarray(shape, dtype=float)
    return float(np.sum(w * phi) / np.sum(w * phi**2))


def c1_factor(te: float, rd: float, ts: float, limit: float) -> float:
    """C1 = 1 for Te > the corner period ``limit``, else [1 + (Rd - 1)·Ts/Te] / Rd."""
    if te > limit:
        return 1.0
    return (1 + (rd - 1) * ts / te) / rd


def rayleigh_period(masses: Any, displacements: Any, forces: Any) -> float:
    """T = 2π·√(Σmᵢuᵢ² / ΣFᵢuᵢ) of the forces ``forces`` causing ``displacements``."""
    m, u, f = (np.asarray(a, dtype=float) for a in (masses, displacements, forces))
    work = float(np.sum(f * u))
    return 2 * math.pi * math.sqrt(float(np.sum(m * u**2)) / work) if work > 0 else 0.0


# ─────────────────────────────── the coefficient method ───────────────────────────────


def _settle(
    at: Callable[[float], tuple[float, dict[str, Any]]], first: float, last: float
) -> tuple[float, dict[str, Any], bool]:
    """The displacement δ that ``at`` (the target found when the curve is idealised up to a
    trial δ) gives back, a root of at(δ) - δ: ``(δt, at's values there, settled)``. Below the
    first increment ``first`` the curve is straight, so at(δ) > δ there; bisection keeps a sign
    change between the ends. A target beyond the curve's end ``last`` is returned unsettled."""
    lo = 1e-3 * first
    hi = last
    dt, values = at(hi)
    converged = dt <= hi
    if converged:
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            found, values = at(mid)
            if found > mid:
                lo = mid
            else:
                hi = mid
            if hi - lo <= 1e-7 * hi:
                break
        dt, values = at(hi)
        # A jump of at(δ) across the root (a coarse curve) leaves dt off hi: not settled.
        converged = abs(dt - hi) <= 1e-3 * hi
    return dt, values, converged


def coefficient(
    displacement: Any,
    shear: Any,
    *,
    t1: float,
    c0: float,
    weight: float,
    spectrum: Callable[[float], float],
    corners: dict[str, float],
    rule: Any,
    **_: Any,
) -> dict[str, Any]:
    """The target displacement of the capacity curve by the displacement coefficient method
    (see the module): ``t1`` [s] the first increment's period, ``c0``, ``weight`` W [N],
    ``spectrum`` Sa(T) [g] with the pack's R and I, ``corners`` the site's TB, TC, TD [s],
    ``rule`` the pack's ``targetDisplacement``. Returns the values of each equation."""
    _needs(rule, "bilinearFitShare", "c1PeriodLimit", "c1Period")
    d, v = np.asarray(displacement, dtype=float), np.asarray(shear, dtype=float)
    if len(d) < 2 or d[1] <= 0 or v[1] <= 0:
        raise ValueError("the capacity curve has no first increment")
    k1 = float(v[1] / d[1])
    limit, ts = corners[rule.c1PeriodLimit], corners[rule.c1Period]

    def target(te: float, fit: dict[str, float] | None) -> tuple[float, float, float, float]:
        sa = spectrum(te)
        rd = max(rule.minimumRd, sa / (fit["Vy"] / weight)) if fit else rule.minimumRd
        c1 = c1_factor(te, rd, ts, limit)
        return c0 * c1 * sa * (te / (2 * math.pi)) ** 2 * G, sa, rd, c1

    last = float(d[-1])

    def at(trial: float) -> tuple[float, dict[str, Any]]:
        """δt of the bilinear fit to ``trial``, with the fit and the factors."""
        fit = bilinear_fit(d, v, trial, rule.bilinearFitShare)
        te = t1 * math.sqrt(k1 / fit["Ke"]) if fit["Ke"] > 0 else t1
        found, sa, rd, c1 = target(te, fit)
        return found, {"fit": fit, "Te": te, "Sa": sa, "Rd": rd, "C1": c1}

    dt, values, converged = _settle(at, float(d[1]), last)
    fit = values["fit"]
    te, sa, rd, c1 = values["Te"], values["Sa"], values["Rd"], values["C1"]
    return {
        "method": "coefficient",
        "T1": t1,
        "K1": k1,
        "V1": float(v[1]),
        "d1": float(d[1]),
        "Vy": fit["Vy"],
        "dy": fit["dy"],
        "Ke": fit["Ke"],
        "Vt": fit["Vt"],
        "elastic": fit["elastic"],
        "Te": te,
        "Sa": sa,
        "C0": c0,
        "C1": c1,
        "Rd": rd,
        "W": weight,
        "target": dt,
        "beyondCurve": dt > last * (1 + 1e-6),
        "converged": converged,
        "bilinear": [[0.0, 0.0], [fit["dy"], fit["Vy"]], [min(dt, last), fit["Vt"]]],
    }


def _needs(rule: Any, *names: str) -> None:
    """ValueError when the pack's ``targetDisplacement`` lacks a value the method needs."""
    missing = [n for n in names if getattr(rule, n, None) is None]
    if missing:
        raise ValueError(
            f"the code pack gives no {', '.join(missing)} for target displacement method "
            f"'{rule.method}'"
        )


def _first_slope(d: np.ndarray, v: np.ndarray) -> float:
    if len(d) < 2 or d[1] <= 0 or v[1] <= 0:
        raise ValueError("the capacity curve has no first increment")
    return float(v[1] / d[1])


# ───────────────────── P3: the displacement coefficient method with C2 ─────────────────────


def c1_site(te: float, mu: float, a: float, period_min: float, period_max: float) -> float:
    """C1 = 1 + (μ - 1)/(a·Te²), Te taken at least ``period_min``; 1 above ``period_max``."""
    if te > period_max:
        return 1.0
    t = max(te, period_min)
    return 1 + (mu - 1) / (a * t**2)


def c2_factor(te: float, mu: float, period_max: float, divisor: float) -> float:
    """C2 = 1 + ((μ - 1)/Te)²/``divisor``; 1 above ``period_max``."""
    if te > period_max:
        return 1.0
    return 1 + ((mu - 1) / te) ** 2 / divisor


def displacement_coefficient(
    displacement: Any,
    shear: Any,
    *,
    t1: float,
    c0: float,
    weight: float,
    spectrum: Callable[[float], float],
    corners: dict[str, float],
    rule: Any,
    site_class: str = "",
    **_: Any,
) -> dict[str, Any]:
    """P3, method ``displacementCoefficient``: δt = C0·C1·C2·Sa(Te)·(Te/2π)²·g on the bilinear
    fit (as :func:`coefficient`), with the strength ratio μ = Sa/(Vy/W)·Cm, C1 by the site
    class factor a and C2 for the cyclic degradation (:class:`~saengine.codes.tables.
    DisplacementCoefficients`)."""
    _needs(rule, "coefficients", "bilinearFitShare")
    k = rule.coefficients
    d, v = np.asarray(displacement, dtype=float), np.asarray(shear, dtype=float)
    k1 = _first_slope(d, v)
    a = k.siteFactors.get(site_class, k.siteFactorDefault)
    last = float(d[-1])

    def at(trial: float) -> tuple[float, dict[str, Any]]:
        fit = bilinear_fit(d, v, trial, rule.bilinearFitShare)
        te = t1 * math.sqrt(k1 / fit["Ke"]) if fit["Ke"] > 0 else t1
        sa = spectrum(te)
        mu = max(1.0, sa / (fit["Vy"] / weight) * k.massFactor) if fit["Vy"] > 0 else 1.0
        c1 = c1_site(te, mu, a, k.c1PeriodMin, k.c1PeriodMax)
        c2 = c2_factor(te, mu, k.c2PeriodMax, k.c2Divisor)
        found = c0 * c1 * c2 * sa * (te / (2 * math.pi)) ** 2 * G
        return found, {"fit": fit, "Te": te, "Sa": sa, "mu": mu, "C1": c1, "C2": c2}

    dt, values, converged = _settle(at, float(d[1]), last)
    fit = values["fit"]
    return {
        "method": "displacementCoefficient",
        "T1": t1,
        "K1": k1,
        "V1": float(v[1]),
        "d1": float(d[1]),
        "Vy": fit["Vy"],
        "dy": fit["dy"],
        "Ke": fit["Ke"],
        "Vt": fit["Vt"],
        "elastic": fit["elastic"],
        "Te": values["Te"],
        "Sa": values["Sa"],
        "C0": c0,
        "C1": values["C1"],
        "C2": values["C2"],
        "Cm": k.massFactor,
        "mu": values["mu"],
        "a": a,
        "W": weight,
        "target": dt,
        "beyondCurve": dt > last * (1 + 1e-6),
        "converged": converged,
        "bilinear": [[0.0, 0.0], [fit["dy"], fit["Vy"]], [min(dt, last), fit["Vt"]]],
    }


# ─────────────────────── P3: equivalent linearisation (performance point) ───────────────────────


def effective_damping_period(mu: float, alpha: float, t0: float, rule: Any) -> tuple[float, float]:
    """βeff [%] and Teff [s] of a bilinear system of ductility ``mu`` and initial period ``t0``
    by the bands of ``rule`` (:class:`~saengine.codes.tables.EquivalentLinearization`);
    ``alpha`` (post-yield stiffness ratio) is not used by these general-form coefficients."""
    del alpha
    beta0 = rule.initialDamping
    if mu <= 1:
        return beta0, t0
    x = mu - 1
    low, high = rule.bands
    if mu < low:
        b1, b2 = rule.low.beta
        p1, p2 = rule.low.period
        return b1 * x**2 + b2 * x**3 + beta0, (p1 * x**2 + p2 * x**3 + 1) * t0
    if mu <= high:
        b1, b2 = rule.mid.beta
        p1, p2 = rule.mid.period
        return b1 + b2 * x + beta0, (p1 + p2 * x + 1) * t0
    b1, b2 = rule.high.beta
    p1, p2 = rule.high.period
    teff = (p1 * (math.sqrt(x / (1 + p2 * (mu - 2))) - 1) + 1) * t0
    f = b2 * x
    return b1 * ((f - 1) / f**2) * (teff / t0) ** 2 + beta0, teff


def damping_reduction(beta: float, rule: Any) -> float:
    """B(βeff) = numerator/(constant - ln βeff[%]): divides the spectral ordinates."""
    return rule.reductionNumerator / (rule.reductionConstant - math.log(beta))


def equivalent_linearization(
    displacement: Any,
    shear: Any,
    *,
    t1: float,
    c0: float,
    weight: float,
    spectrum: Callable[[float], float],
    corners: dict[str, float],
    rule: Any,
    first: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """P3, method ``equivalentLinearization``: the performance point of the capacity curve.

    The curve becomes a capacity spectrum (Sa = V/(α1·W), Sd = δ/PF, PF = C0 of the shape with
    1 at the control point, α1 = (Σwφ)²/(W·Σwφ²)). For a trial displacement the bilinear fit
    gives the yield point, the initial period T0 = 2π·√(Sdy/(Say·g)), the ductility μ and the
    post-yield ratio α; the effective damping and period follow (:func:`effective_damping_period`),
    the spectrum is reduced by B(βeff), and the modified spectrum (× M = (Teff/Tsec)²) meets
    the secant period line at Sd = Sa(Teff)/B·(Teff/2π)²·g. The performance point is the trial
    that gives itself back."""
    _needs(rule, "linearization", "bilinearFitShare")
    lin = rule.linearization
    d, v = np.asarray(displacement, dtype=float), np.asarray(shear, dtype=float)
    k1 = _first_slope(d, v)
    weights = np.asarray((first or {}).get("weights") or [], dtype=float)
    shape = np.asarray((first or {}).get("shape") or [], dtype=float)
    if len(weights) and len(weights) == len(shape) and float(np.sum(weights * shape**2)) > 0:
        alpha1 = float(np.sum(weights * shape) ** 2 / (weight * np.sum(weights * shape**2)))
    else:
        alpha1 = 1.0
    pf = c0
    last = float(d[-1])

    def at(trial: float) -> tuple[float, dict[str, Any]]:
        fit = bilinear_fit(d, v, trial, rule.bilinearFitShare)
        say = fit["Vy"] / (alpha1 * weight)
        sdy = fit["dy"] / pf
        t0 = 2 * math.pi * math.sqrt(sdy / (say * G)) if say > 0 and sdy > 0 else t1
        mu = trial / fit["dy"] if fit["dy"] > 0 and not fit["elastic"] else 1.0
        post = (
            (fit["Vt"] - fit["Vy"]) / (trial - fit["dy"]) / fit["Ke"]
            if trial > fit["dy"] and fit["Ke"] > 0
            else 0.0
        )
        beta, teff = effective_damping_period(mu, post, t0, lin)
        b = damping_reduction(beta, lin)
        sa = spectrum(teff)
        sd = sa / b * (teff / (2 * math.pi)) ** 2 * G
        tsec = t0 * math.sqrt(mu / (1 + post * mu - post)) if mu > 1 else t0
        m = (teff / tsec) ** 2 if tsec > 0 else 1.0
        return pf * sd, {
            "fit": fit,
            "T0": t0,
            "Te": teff,
            "Tsec": tsec,
            "beta": beta,
            "B": b,
            "M": m,
            "mu": mu,
            "alpha": post,
            "Sa": sa,
            "Sd": sd,
            "Saeff": m * sa / b,
        }

    dt, values, converged = _settle(at, float(d[1]), last)
    fit = values["fit"]
    return {
        "method": "equivalentLinearization",
        "T1": t1,
        "K1": k1,
        "Vy": fit["Vy"],
        "dy": fit["dy"],
        "Ke": fit["Ke"],
        "Vt": fit["Vt"],
        "elastic": fit["elastic"],
        "T0": values["T0"],
        "Te": values["Te"],
        "Tsec": values["Tsec"],
        "beta": values["beta"],
        "B": values["B"],
        "M": values["M"],
        "mu": values["mu"],
        "alpha": values["alpha"],
        "Sa": values["Sa"],
        "Sd": values["Sd"],
        "SaPerformance": values["Saeff"],
        "C0": c0,
        "PF": pf,
        "alpha1": alpha1,
        "W": weight,
        "target": dt,
        "beyondCurve": dt > last * (1 + 1e-6),
        "converged": converged,
        "bilinear": [[0.0, 0.0], [fit["dy"], fit["Vy"]], [min(dt, last), fit["Vt"]]],
    }


# ─────────────────────────── P3: the N2 method (equivalent SDOF) ───────────────────────────


def n2_idealisation(ds: np.ndarray, fs: np.ndarray, dm: float) -> tuple[float, float]:
    """The elasto-perfectly plastic idealisation of the SDOF curve (``ds``, ``fs``) up to
    ``dm``: Fy* the largest force up to dm and dy* = 2·(dm - Em/Fy*), Em the area under the
    curve to dm (equal energies). Returns ``(Fy*, dy*)``."""
    dd, ff = _upto(ds, fs, dm)
    fy = float(np.max(ff))
    em = float(np.trapezoid(ff, dd))
    dy = 2 * (dm - em / fy) if fy > 0 else dm
    return fy, min(max(dy, 1e-9 * dm), dm)


def n2_target(
    t_star: float, se: float, fy_over_m: float, tc: float, cap: float | None
) -> tuple[float, float, float]:
    """dt* [m] of the SDOF of period ``t_star`` [s] with the elastic spectral acceleration
    ``se`` [g] and the yield acceleration ``fy_over_m`` [m/s²]: ``(dt*, det*, qu)``."""
    det = se * G * (t_star / (2 * math.pi)) ** 2
    qu = se * G / fy_over_m if fy_over_m > 0 else 1.0
    if t_star >= tc or qu <= 1:
        dt = det
    else:
        dt = max(det, det / qu * (1 + (qu - 1) * tc / t_star))
    if cap is not None:
        dt = min(dt, cap * det)
    return dt, det, qu


def n2(
    displacement: Any,
    shear: Any,
    *,
    t1: float,
    c0: float,
    weight: float,
    spectrum: Callable[[float], float],
    corners: dict[str, float],
    rule: Any,
    first: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """P3, method ``n2``: the equivalent SDOF system (Γ = Σmφ/Σmφ² with φ = 1 at the control
    point, m* = Σmφ, F* = V/Γ, d* = δ/Γ), its elasto-perfectly plastic idealisation
    (:func:`n2_idealisation`), T* = 2π·√(m*·dy*/Fy*), dt* from the elastic spectrum
    (:func:`n2_target`) and dt = Γ·dt*. With ``n2.iterate`` the idealisation is taken to dm* =
    dt* until the target settles; else to the displacement at the peak of the curve."""
    _needs(rule, "n2")
    rule_n2 = rule.n2
    d, v = np.asarray(displacement, dtype=float), np.asarray(shear, dtype=float)
    k1 = _first_slope(d, v)
    weights = np.asarray((first or {}).get("weights") or [], dtype=float)
    shape = np.asarray((first or {}).get("shape") or [], dtype=float)
    m_star = float(np.sum(weights * shape)) / G if len(weights) == len(shape) else 0.0
    if m_star <= 0:
        m_star = weight / G / c0
    gamma = c0
    ds, fs = d / gamma, v / gamma
    tc = corners[rule_n2.cornerPeriod]
    last = float(d[-1])

    def at(trial: float) -> tuple[float, dict[str, Any]]:
        fy, dy = n2_idealisation(ds, fs, trial / gamma)
        t_star = 2 * math.pi * math.sqrt(m_star * dy / fy) if fy > 0 else t1
        se = spectrum(t_star)
        dt, det, qu = n2_target(t_star, se, fy / m_star, tc, rule_n2.maxElasticMultiple)
        return gamma * dt, {
            "Fy": fy,
            "dy": dy,
            "T": t_star,
            "Se": se,
            "det": det,
            "qu": qu,
            "dtStar": dt,
            "dm": trial / gamma,
        }

    if rule_n2.iterate:
        dt, values, converged = _settle(at, float(d[1]), last)
    else:
        dt, values = at(float(d[int(np.argmax(v))]))
        converged = True
    fy, dy = values["Fy"], values["dy"]
    return {
        "method": "n2",
        "T1": t1,
        "K1": k1,
        "Gamma": gamma,
        "mStar": m_star,
        "FyStar": fy,
        "dyStar": dy,
        "dmStar": values["dm"],
        "Tstar": values["T"],
        "Se": values["Se"],
        "det": values["det"],
        "qu": values["qu"],
        "dtStar": values["dtStar"],
        "Vy": gamma * fy,
        "dy": gamma * dy,
        "Ke": fy / dy if dy > 0 else 0.0,
        "elastic": values["qu"] <= 1,
        "Te": values["T"],
        "Sa": values["Se"],
        "C0": gamma,
        "TC": tc,
        "W": weight,
        "target": dt,
        "beyondCurve": dt > last * (1 + 1e-6),
        "converged": converged,
        "bilinear": [[0.0, 0.0], [gamma * dy, gamma * fy], [min(dt, last), gamma * fy]],
    }


#: Target displacement methods by the id a code pack gives (``targetDisplacement.method``).
METHODS: dict[str, Callable[..., dict[str, Any]]] = {
    "coefficient": coefficient,
    "displacementCoefficient": displacement_coefficient,
    "equivalentLinearization": equivalent_linearization,
    "n2": n2,
}


def capacity_checks(
    displacement: Any, shear: Any, target: float, push_share: float, drop_share: float | None
) -> dict[str, Any]:
    """Whether the capacity curve reaches ``push_share`` × ``target`` and whether its base
    shear drops in any step up to ``drop_share`` × ``target``: ``{"pushedTo", "required",
    "reached", "noDropTo", "dropAt" (displacement of the first drop, or None), "noDrop"
    (None when the curve stops before the no-drop range ends), "targetStep" (the first step at
    or beyond the target, or None)}``."""
    d, v = np.asarray(displacement, dtype=float), np.asarray(shear, dtype=float)
    pushed = float(d[-1])
    required = push_share * target
    step = next((k for k in range(len(d)) if d[k] >= target * (1 - 1e-9)), None)
    if drop_share is None:  # P3: the code has no no-drop rule
        return {
            "pushedTo": pushed,
            "required": required,
            "reached": pushed >= required * (1 - 1e-3),
            "noDropTo": None,
            "dropAt": None,
            "noDrop": None,
            "targetStep": step,
        }
    limit = drop_share * target
    tolerance = 1e-3 * float(np.max(np.abs(v))) if len(v) else 0.0
    drop = None
    for k in range(1, len(d)):
        if d[k] > limit * (1 + 1e-9):
            break
        if v[k] < v[k - 1] - tolerance:
            drop = float(d[k])
            break
    covered = pushed >= limit * (1 - 1e-6)
    return {
        "pushedTo": pushed,
        "required": required,
        "reached": pushed >= required * (1 - 1e-3),
        "noDropTo": limit,
        "dropAt": drop,
        "noDrop": False if drop is not None else (True if covered else None),
        "targetStep": step,
    }


# ─────────────────────────────── from a pushover run ───────────────────────────────


def first_increment(
    project: dict[str, Any], analysis: dict[str, Any], results: Any
) -> dict[str, Any]:
    """The masses, shape and period of the first increment of a pushover run (``results``, a
    ``PushoverResults`` of ``analysis`` in the model ``project``): ``{"weights", "shape",
    "C0", "T1", "W"}`` over the nodes with mass in the pushed direction."""
    dof = int(analysis["control_dof"]) - 1
    control = int(analysis["control_node"])
    sign = 1.0 if float(analysis.get("target_disp", 1.0)) >= 0 else -1.0
    patterns = {p["id"]: p for p in project.get("load_patterns", [])}
    reference: dict[int, float] = {}
    for pid in analysis.get("pattern_ids", []):
        for load in patterns.get(pid, {}).get("nodal_loads", []):
            node = int(load["node_id"])
            reference[node] = reference.get(node, 0.0) + float(load["forces"][dof])
    nodes = {int(n["id"]): n for n in project.get("nodes", [])}

    def moved(node: int) -> float:
        rows = np.asarray(results.node_disp[node], dtype=float)
        return sign * float(rows[1][dof] - rows[0][dof])

    roof = moved(control)
    if roof <= 0:
        raise ValueError("the control point does not move in the first increment")
    masses, shape, disp = [], [], []
    for node_id, node in sorted(nodes.items()):
        mass = float((node.get("mass") or [0.0] * 6)[dof])
        if mass <= 0 or node_id not in results.node_disp:
            continue
        u = moved(node_id)
        masses.append(mass)
        disp.append(u)
        shape.append(u / roof)
    total = sum(reference.values())
    v1 = sign * float(np.asarray(results.base_shear)[1])
    forces = [v1 * reference.get(n, 0.0) / total if total else 0.0 for n in sorted(reference)]
    displaced = [moved(n) if n in results.node_disp else 0.0 for n in sorted(reference)]
    work = float(np.dot(forces, displaced))
    kinetic = float(np.dot(masses, np.square(disp)))
    t1 = 2 * math.pi * math.sqrt(kinetic / work) if work > 0 else 0.0
    weights = [m * G for m in masses]
    return {
        "weights": weights,
        "shape": shape,
        "C0": c0_factor(weights, shape),
        "T1": t1,
        "W": sum(weights),
    }


def capacity_curve(analysis: dict[str, Any], results: Any) -> tuple[np.ndarray, np.ndarray]:
    """The capacity curve of a pushover run from its state under gravity: control point
    displacement and base shear, both positive in the pushed direction."""
    sign = 1.0 if float(analysis.get("target_disp", 1.0)) >= 0 else -1.0
    d = np.asarray(results.control_disp, dtype=float)
    v = np.asarray(results.base_shear, dtype=float)
    return sign * (d - d[0]), sign * v


def spectrum_of(settings: Any, rule: Any) -> tuple[Callable[[float], float], dict[str, float]]:
    """Sa(T) [g] of the project's site with the pack's R and I for the target displacement,
    and the site class's corner periods."""
    from saengine.codes import context as code_context
    from saengine.fem.loads import design_acceleration
    from saengine.library.settings import derived

    values = derived(settings)
    z = values.get("Z")
    if not z:
        raise ValueError("the site has no seismic zone coefficient")
    site_class = settings.site.siteClass
    damping = settings.seismic.damping
    site = code_context.table("seismic").siteClasses[site_class]

    def sa(period: float) -> float:
        return design_acceleration(
            period, site_class, z, rule.spectrumImportance, rule.spectrumR, damping
        )

    corners = {"TB": site.TB, "TC": site.TC, "TD": site.TD}
    if not site.TC and hasattr(z, "sd1") and float(z) > 0:
        # P3: a mapped spectrum (the site's SDS, SD1, TL) has its corners from the values:
        # TS = SD1/SDS, T0 the share of TS the pack's design spectrum gives, TL.
        ts = z.sd1 / float(z)
        spectrum_rule = getattr(code_context.table("seismic"), "designSpectrum", None)
        share = getattr(spectrum_rule, "t0Share", None) or 0.0
        corners = {"TB": share * ts, "TC": ts, "TD": z.tl or 0.0}
    return sa, corners


def evaluate(
    project: dict[str, Any], analysis: dict[str, Any], results: Any, settings: Any
) -> dict[str, Any]:
    """The target displacement and the capacity checks of one pushover run, by the method of
    the code pack in force. ``{"available": False, "reason"}`` when the pack has no pushover
    method or the run cannot give one."""
    rule = table()
    if rule is None:
        return {"available": False, "reason": "the code pack does not cover pushover analysis"}
    method = METHODS.get(rule.targetDisplacement.method)
    if method is None:
        return {
            "available": False,
            "reason": f"target displacement method '{rule.targetDisplacement.method}' unknown",
        }
    if settings is None:
        return {"available": False, "reason": "the project settings could not be read"}
    hazards: list[dict[str, Any]] = []
    try:
        d, v = capacity_curve(analysis, results)
        first = first_increment(project, analysis, results)
        sa, corners = spectrum_of(settings, rule.targetDisplacement)

        def run(scale: float) -> dict[str, Any]:
            def scaled(period: float) -> float:
                return scale * sa(period)

            return method(
                d,
                v,
                t1=first["T1"],
                c0=first["C0"],
                weight=first["W"],
                spectrum=sa if scale == 1.0 else scaled,
                corners=corners,
                rule=rule.targetDisplacement,
                site_class=settings.site.siteClass,
                first=first,
            )

        levels = rule.targetDisplacement.hazards
        found = run(levels[0].spectrumScale if levels else 1.0)
        # P3: the target of every hazard level, the first the main one.
        for k, level in enumerate(levels):
            each = found if k == 0 else run(level.spectrumScale)
            hazards.append(
                {
                    "id": level.id,
                    "label": level.label,
                    "level": level.level,
                    "scale": level.spectrumScale,
                    "target": each["target"],
                    "beyondCurve": each["beyondCurve"],
                    "converged": each["converged"],
                    "targetStep": next(
                        (i for i in range(len(d)) if d[i] >= each["target"] * (1 - 1e-9)), None
                    ),
                }
            )
    except (ValueError, KeyError, IndexError, ZeroDivisionError) as error:
        return {"available": False, "reason": str(error)}
    checks = capacity_checks(
        d, v, found["target"], rule.procedure.pushToTarget, rule.procedure.noDropToTarget
    )
    notes = []
    names = {p["id"]: p.get("name", "") for p in project.get("load_patterns", [])}
    used = [names.get(pid, "") for pid in analysis.get("pattern_ids", [])]
    kind = {"M": "firstMode", "E": "seismic", "U": "uniform"}
    pattern = kind.get(used[0][:1], "") if len(used) == 1 else ""
    pattern_ok = pattern == rule.procedure.loadPattern
    if not pattern_ok:
        notes.append(
            f"The code pack requires the '{rule.procedure.loadPattern}' load pattern "
            f"({clause('pattern')}); this pushover uses '{pattern or 'another'}': choose it in "
            "the project settings (Analysis, Pushover) and derive again."
        )
    if found["beyondCurve"]:
        notes.append(
            "The target displacement lies beyond the end of the capacity curve: push further "
            "(raise the target roof drift) or the structure cannot reach it."
        )
    elif not checks["reached"]:
        notes.append(
            f"The pushover must go to at least {rule.procedure.pushToTarget:g} × the target "
            f"displacement ({checks['required']:.3f} m) and stopped at "
            f"{checks['pushedTo']:.3f} m: raise the target roof drift ({clause('pushTo')})."
        )
    if checks["noDrop"] is False:
        notes.append(
            f"The base shear drops at {checks['dropAt']:.3f} m, before "
            f"{rule.procedure.noDropToTarget:g} × the target displacement: the structure "
            f"must be strengthened ({clause('noDrop')})."
        )
    if not found["converged"] and not found["beyondCurve"]:
        notes.append("The target displacement did not settle; the last value is shown.")
    if checks["targetStep"] is not None and checks["targetStep"] < MIN_STEPS_TO_TARGET:
        notes.append(
            f"The pushover reaches the target displacement in {checks['targetStep']} "
            f"step{'s' if checks['targetStep'] != 1 else ''}: the curve is too coarse to fit "
            "and to show the members yielding on the way. Use more steps or a smaller target "
            "roof drift."
        )
    for hazard in hazards[1:]:
        if hazard["beyondCurve"]:
            notes.append(
                f"The target displacement of {hazard['label'] or hazard['id']} lies beyond the "
                "end of the capacity curve: push further to check it."
            )
    keys = ["target", "period", "c0", "c1", "rd", "pushTo", "noDrop"]
    extra: dict[str, Any] = {}
    if rule.targetDisplacement.method != "coefficient":
        # P3: the other methods' clauses, the hazard levels and the performance point.
        keys = [*keys, "c2", "damping", "sdof", "idealisation", "hazards"]
        extra = {
            "hazards": hazards,
            "performancePoint": [found["target"], float(np.interp(found["target"], d, v))],
        }
    return {
        "available": True,
        **found,
        **checks,
        **extra,
        "corners": corners,
        "clauses": {k: clause(k) for k in keys},
        "note": rule.targetDisplacement.note,
        "notes": notes,
        "pattern": pattern,
        "patternOk": pattern_ok,
        "ok": (
            pattern_ok
            and not found["beyondCurve"]
            and bool(checks["reached"])
            and checks["noDrop"] is not False
        ),
    }

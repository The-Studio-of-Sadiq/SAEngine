"""P5: spectra of records and pairs, and spectral matching of a record to a target spectrum.

Generic: what a suite must meet and how its records are modified come from the code pack in
force (``seismic.timeHistory``, :class:`saengine.codes.tables.TimeHistoryRules`, and its
``matching``, :class:`saengine.codes.tables.SpectralMatching`); this module only computes.

- **Oscillators.** The damped linear SDOF response to a record by the piecewise-exact
  recurrence of Nigam and Jennings (1969), the coefficients of OpenSees Studio's
  :mod:`opensees_studio.core.response_spectrum`, run as a recursive filter (scipy's
  ``lfilter``) so that many periods and records cost little; it gives the same displacements
  as the step-by-step recurrence.
- **Pairs** (:func:`pair_spectrum`): the SRSS of the two components' spectra (``srss``), the
  maximum-direction spectrum (``maxDirection``: RotD100, the largest response over all
  horizontal directions; since max over the angle of u1·cos θ + u2·sin θ is the length of the
  vector (u1, u2), it is ω² times the peak of that length) or each component's own
  (``eachComponent``: the smaller of the two at each period, so that both components' means
  meet the criterion when this one does).
- **Spectral matching** by method id (:data:`METHODS`): ``frequencyDomain``: the record is
  first fitted to the target over the range by one amplitude factor (in log space), then its
  Fourier amplitudes are multiplied by the ratio of the target to its spectrum (interpolated
  in log frequency, tapered to 1 over half an octave outside the matching range) and the
  baseline is corrected; repeated until every ordinate of the procedure's range is within the
  tolerance of the target, the best iteration kept. (Time-domain wavelet matching is not
  built; it stays a planned feature.)

  The baseline correction takes the polynomial t² … t^n (n: the pack's ``baselineOrder``,
  at least 2) that best fits the displacement off the acceleration (its second derivative),
  so the record ends with no drift in displacement.

Accelerations are in g, periods in s.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: Below this the ordinate of a spectrum is taken as zero (g).
TINY = 1e-12


# ─────────────────────────────────────── oscillators ───────────────────────────────────────


def _filters(periods: np.ndarray, damping: float, dt: float) -> list[tuple[np.ndarray, ...]]:
    """Per period, the recursive filter of the Nigam-Jennings recurrence of the relative
    displacement: ``(numerator, denominator, start correction numerator)``."""
    from opensees_studio.core.response_spectrum import _nigam_jennings_coefficients

    omega = 2.0 * np.pi / np.asarray(periods, dtype=float)
    a11, a12, a21, a22, b11, b12, b21, b22 = _nigam_jennings_coefficients(omega, damping, dt)
    out = []
    for k in range(omega.size):
        num = np.array(
            [b12[k], b11[k] - a22[k] * b12[k] + a12[k] * b22[k], a12[k] * b21[k] - a22[k] * b11[k]]
        )
        den = np.array([1.0, -(a11[k] + a22[k]), a11[k] * a22[k] - a12[k] * a21[k]])
        start = np.array([b12[k], a12[k] * b22[k] - a22[k] * b12[k]])
        out.append((num, den, start))
    return out


def displacements(
    dt: float, accel: np.ndarray, periods: Sequence[float], damping: float
) -> np.ndarray:
    """The relative displacement histories (periods × samples) of the oscillators of
    ``periods`` [s] under ``accel`` (from rest; the units of ``accel`` times s²)."""
    from scipy.signal import lfilter

    a = np.asarray(accel, dtype=float)
    impulse = np.zeros(a.size)
    impulse[0] = 1.0
    rows = []
    for num, den, start in _filters(np.asarray(periods, dtype=float), damping, dt):
        u = lfilter(num, den, a)
        if a[0] != 0.0:
            u = u - a[0] * lfilter(start, den, impulse)
        rows.append(u)
    return np.asarray(rows)


def spectrum(dt: float, accel: np.ndarray, periods: Sequence[float], damping: float) -> np.ndarray:
    """The pseudo-acceleration spectrum of ``accel`` at ``periods`` (the units of ``accel``)."""
    t = np.asarray(periods, dtype=float)
    u = displacements(dt, accel, t, damping)
    return (2.0 * np.pi / t) ** 2 * np.abs(u).max(axis=1)


def max_direction_spectrum(
    dt: float, first: np.ndarray, second: np.ndarray, periods: Sequence[float], damping: float
) -> np.ndarray:
    """The maximum-direction (RotD100) pseudo-acceleration spectrum of two orthogonal
    components sampled at the same ``dt`` (the shorter length is used)."""
    n = min(len(first), len(second))
    t = np.asarray(periods, dtype=float)
    u1 = displacements(dt, np.asarray(first, dtype=float)[:n], t, damping)
    u2 = displacements(dt, np.asarray(second, dtype=float)[:n], t, damping)
    return (2.0 * np.pi / t) ** 2 * np.sqrt(u1**2 + u2**2).max(axis=1)


def _resampled(record: tuple[float, np.ndarray], dt: float) -> np.ndarray:
    """``record`` linearly interpolated at the step ``dt``."""
    step, values = record
    values = np.asarray(values, dtype=float)
    if abs(step - dt) <= 1e-12 * max(step, dt):
        return values
    span = (values.size - 1) * step
    t = np.arange(0.0, span + dt / 2, dt)
    return np.interp(t, np.arange(values.size) * step, values)


def pair_spectrum(
    first: tuple[float, np.ndarray],
    second: tuple[float, np.ndarray],
    periods: Sequence[float],
    damping: float,
    combination: str = "srss",
) -> np.ndarray:
    """The spectrum of a pair (each component ``(dt, accel)``) by ``combination``: ``srss``,
    ``maxDirection`` or ``eachComponent`` (see the module doc)."""
    if combination == "maxDirection":
        dt = min(first[0], second[0])
        return max_direction_spectrum(
            dt, _resampled(first, dt), _resampled(second, dt), periods, damping
        )
    s1 = spectrum(first[0], first[1], periods, damping)
    s2 = spectrum(second[0], second[1], periods, damping)
    if combination == "eachComponent":
        return np.minimum(s1, s2)
    return np.sqrt(s1**2 + s2**2)


def component_share(combination: str) -> float:
    """The share of the pair's criterion each component is matched to, so that the pair's
    spectrum meets it when both components match: 1/√2 for the SRSS, 1 for the maximum
    direction (never below either component's own spectrum) and for each component."""
    return 1.0 / np.sqrt(2.0) if combination == "srss" else 1.0


# ─────────────────────────────────────── baseline ───────────────────────────────────────


def baseline_corrected(dt: float, accel: np.ndarray, order: int = 3) -> np.ndarray:
    """``accel`` less the second derivative of the polynomial c2·t² + … + cn·tⁿ (n =
    max(order, 2)) that best fits its displacement (least squares), then plus the line α + β·t
    that brings its velocity and displacement to zero at the end, so that the corrected record
    has no drift in velocity and displacement."""
    a = np.asarray(accel, dtype=float)
    t = np.arange(a.size) * dt
    velocity = np.concatenate([[0.0], np.cumsum(0.5 * (a[1:] + a[:-1]) * dt)])
    displacement = np.concatenate([[0.0], np.cumsum(0.5 * (velocity[1:] + velocity[:-1]) * dt)])
    powers = list(range(2, max(int(order), 2) + 1))
    span = t[-1] if t[-1] > 0 else 1.0
    basis = np.column_stack([(t / span) ** p for p in powers])
    coeffs, *_ = np.linalg.lstsq(basis, displacement, rcond=None)
    second = sum(
        c * p * (p - 1) * (t / span) ** (p - 2) / span**2
        for c, p in zip(coeffs, powers, strict=True)
    )
    out = a - second
    # Then a linear correction α + β·t so that the record ends at rest: v(T) = d(T) = 0.
    v, d = _integrals(out, dt)
    end = span
    matrix = np.array([[end, end**2 / 2], [end**2 / 2, end**3 / 6]])
    alpha, beta = np.linalg.solve(matrix, [-v[-1], -d[-1]])
    return out + alpha + beta * t


def _integrals(a: np.ndarray, dt: float) -> tuple[np.ndarray, np.ndarray]:
    """Velocity and displacement of ``a`` from rest (trapezoidal rule)."""
    velocity = np.concatenate([[0.0], np.cumsum(0.5 * (a[1:] + a[:-1]) * dt)])
    displacement = np.concatenate([[0.0], np.cumsum(0.5 * (velocity[1:] + velocity[:-1]) * dt)])
    return velocity, displacement


# ─────────────────────────────────────── matching ───────────────────────────────────────


@dataclass
class MatchResult:
    """A matched record: ``accel`` [g] at the record's ``dt``; ``periods`` [s] of the matching
    range with the ``goal``, the spectrum ``before`` and ``after`` [g]; ``misfit``: the largest
    |Sa / goal - 1| over the range after matching; ``history``: the misfit per iteration."""

    dt: float
    accel: np.ndarray
    periods: list[float]
    goal: list[float]
    before: list[float]
    after: list[float]
    misfit: float
    iterations: int
    converged: bool
    method: str
    history: list[float] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "iterations": self.iterations,
            "misfit": self.misfit,
            "converged": self.converged,
            "history": self.history,
            "periods": self.periods,
            "goal": self.goal,
            "before": self.before,
            "after": self.after,
        }


def _misfit(sa: np.ndarray, goal: np.ndarray) -> float:
    return float(np.max(np.abs(sa / np.maximum(goal, TINY) - 1.0)))


def _frequency_ratio(
    freqs: np.ndarray, periods: np.ndarray, ratio: np.ndarray, taper: float = 0.5
) -> np.ndarray:
    """The ratio of target to record at the Fourier frequencies ``freqs`` [Hz]: interpolated in
    log frequency over the matching range, going to 1 over ``taper`` octaves outside it."""
    f = 1.0 / periods[::-1]
    r = np.log(np.maximum(ratio[::-1], TINY))
    out = np.ones(freqs.size)
    inside = freqs > 0
    lf = np.log2(np.where(inside, freqs, 1.0))
    l0, l1 = np.log2(f[0]), np.log2(f[-1])
    log_ratio = np.interp(lf, np.log2(f), r)
    weight = np.clip(1.0 - np.maximum(l0 - lf, lf - l1) / taper, 0.0, 1.0)
    weight = np.where((lf >= l0) & (lf <= l1), 1.0, weight)
    out[inside] = np.exp(weight[inside] * log_ratio[inside])
    return out


def _frequency_domain(
    dt: float,
    accel: np.ndarray,
    periods: np.ndarray,
    goal: np.ndarray,
    rule: Any,
    damping: float,
    measure: Callable[[np.ndarray], float],
) -> tuple[np.ndarray, list[float]]:
    a = np.asarray(accel, dtype=float).copy()
    n = a.size
    size = 1 << int(np.ceil(np.log2(2 * n)))
    freqs = np.fft.rfftfreq(size, dt)
    best, best_misfit, history = a.copy(), np.inf, []
    for _ in range(int(rule.iterations)):
        sa = spectrum(dt, a, periods, damping)
        misfit = measure(sa)
        history.append(misfit)
        if misfit < best_misfit:
            best, best_misfit = a.copy(), misfit
        if misfit <= rule.tolerance:
            break
        ratio = goal / np.maximum(sa, TINY)
        spectrum_f = np.fft.rfft(a, size) * _frequency_ratio(freqs, periods, ratio)
        a = baseline_corrected(dt, np.fft.irfft(spectrum_f, size)[:n], rule.baselineOrder)
    else:
        sa = spectrum(dt, a, periods, damping)
        misfit = measure(sa)
        history.append(misfit)
        if misfit < best_misfit:
            best = a.copy()
    return best, history


#: Spectral matching methods by the pack's ``matching.method`` id.
METHODS: dict[str, Callable[..., tuple[np.ndarray, list[float]]]] = {
    "frequencyDomain": _frequency_domain,
}


def match(
    dt: float,
    accel: np.ndarray,
    goal: Callable[[np.ndarray], np.ndarray],
    low: float,
    high: float,
    rule: Any,
    damping: float,
) -> MatchResult:
    """``accel`` [g] matched to the spectrum ``goal`` (periods [s] -> Sa [g]) by the pack's
    ``rule`` (:class:`saengine.codes.tables.SpectralMatching`): over ``rule.lowerShare`` ×
    ``low`` to ``rule.upperShare`` × ``high`` [s], the misfit measured from ``low`` to ``high``
    (the procedure's period range). Raises ``ValueError`` for an unknown method, an empty
    range or a record without motion."""
    method = METHODS.get(rule.method)
    if method is None:
        raise ValueError(f"spectral matching method '{rule.method}' unknown")
    if not (0 < low < high):
        raise ValueError("spectral matching needs a period range")
    a = np.asarray(accel, dtype=float)
    if a.size < 4 or not np.any(a):
        raise ValueError("the record has no motion")
    periods = np.geomspace(rule.lowerShare * low, rule.upperShare * high, int(rule.points))
    target = np.asarray(goal(periods), dtype=float)
    if np.any(target <= 0):
        raise ValueError("the target spectrum is zero in the matching range")
    before = spectrum(dt, a, periods, damping)
    if np.any(before <= TINY):
        raise ValueError("the record has no response in the matching range")
    inside = (periods >= low * (1 - 1e-9)) & (periods <= high * (1 + 1e-9))
    if not np.any(inside):
        inside = np.ones(periods.size, dtype=bool)

    def measure(sa: np.ndarray) -> float:
        return _misfit(sa[inside], target[inside])

    # First the amplitude that fits the record to the goal over the range (in log space).
    fitted = a * float(np.exp(np.mean(np.log(target / before))))
    matched, history = method(dt, fitted, periods, target, rule, damping, measure)
    after = spectrum(dt, matched, periods, damping)
    misfit = measure(after)
    return MatchResult(
        dt=float(dt),
        accel=matched,
        periods=[float(p) for p in periods],
        goal=[float(v) for v in target],
        before=[float(v) for v in before],
        after=[float(v) for v in after],
        misfit=misfit,
        iterations=len(history),
        converged=misfit <= rule.tolerance,
        method=str(rule.method),
        history=[float(m) for m in history],
    )

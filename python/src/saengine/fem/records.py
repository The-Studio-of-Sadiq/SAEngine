"""Ground motion records and suites for the response history procedures (B19).

The engine is generic: what a suite must satisfy comes from the code pack in force (its
``seismic.timeHistory`` rules, :class:`saengine.codes.tables.TimeHistoryRules`), and the
spectra and the period-range scaling are OpenSees Studio's (:mod:`opensees_studio.core.
response_spectrum`, :mod:`opensees_studio.core.scaling`), not a copy of them.

- **Suites.** The time histories of a project form one suite per direction ("X", "Y": one
  horizontal record each, a two-dimensional suite) and one of pairs ("XY": a record with its
  orthogonal component, applied simultaneously, a three-dimensional suite). A suite needs the
  pack's ``minimumRecords`` (BNBC 2020 Part 6 Sec 2.5.10.2: at least three).
- **Scaling** (``method`` "periodRange"): at every period from ``periodLower``·T to
  ``periodUpper``·T the mean of the records' ``spectrumDamping``-damped spectra (of a pair, the
  SRSS of its two components, one factor on both) is not below ``singleRatio`` (pairs:
  ``pairRatio``) times the target spectrum. The target is the design spectrum of the site
  (``targets.linear``: the building's own R and I) or, for the nonlinear procedure, the one
  with the pack's R and I (``targets.nonlinear``; BNBC Sec 2.5.11.2: R = 1, I = 1). T is the
  fundamental period of the direction (of the structure for pairs).
- **Design value** (:func:`design_value`): the largest of the records' peaks below ``meanFrom``
  records (or pairs), their mean from it (BNBC Sec 2.5.10.3: seven).
- **Base shear** (:func:`base_shear_factor`): where the suite's base shear Vth is below
  ``baseShearShare``·V (V the equivalent static base shear), every response times
  share·V/Vth (BNBC Sec 2.5.10.3).

Accelerations are in g here unless a name says otherwise (``*_ms2``: m/s²).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from saengine.codes import context as code_context

G = 9.80665  # m/s²

#: Points of the period grid of a suite check.
CHECK_POINTS = 60
#: A suite within this share of the criterion meets it.
TOLERANCE = 1e-3


def rules() -> Any | None:
    """The ``seismic.timeHistory`` rules of the code pack in force, or None when the pack does
    not cover the response history procedures."""
    try:
        return getattr(code_context.table("seismic"), "timeHistory", None)
    except (KeyError, ValueError):
        return None


def clause(key: str) -> str:
    """The pack's clause reference of a time-history result (``""`` when it has none)."""
    found = rules()
    return str(found.clauses.get(key, "")) if found is not None else ""


# ─────────────────────────────────────── suites ───────────────────────────────────────


def suite_key(history: Any) -> str:
    """The suite a time history belongs to: "XY" for a pair, else its direction."""
    return "XY" if getattr(history, "recordOrthogonal", None) else str(history.direction)


def suites(histories: Sequence[Any]) -> dict[str, list[int]]:
    """The indices of ``histories`` by suite ("X", "Y", "XY"), in their order."""
    out: dict[str, list[int]] = {}
    for k, history in enumerate(histories):
        out.setdefault(suite_key(history), []).append(k)
    return out


def scaled_to_code(history: Any, settings: Any, procedure: str = "linear") -> bool:
    """Whether a history is scaled to the code spectrum: its ``scaling`` "code", or "auto"
    when the earthquake design uses the time histories or for the nonlinear procedure (B36),
    whose records must match the real design spectrum."""
    scaling = getattr(history, "scaling", "manual")
    if scaling == "auto" and procedure == "nonlinear":
        return True
    if scaling == "auto":
        analysis = getattr(settings, "analysis", None)
        return getattr(analysis, "seismicDesign", "static") == "timeHistory"
    return scaling == "code"


def design_rule(count: int, mean_from: int | None = None) -> str:
    """ "max" below the pack's ``meanFrom`` records (or pairs), "mean" from it (``mean_from``:
    another procedure's own number)."""
    if mean_from is None:
        found = rules()
        mean_from = found.meanFrom if found is not None else 7
    return "mean" if count >= mean_from else "max"


def design_value(peaks: Any, rule: str | None = None) -> np.ndarray:
    """The design value of the records' peaks (axis 0 runs over the records): their largest or
    their mean, by :func:`design_rule` unless ``rule`` is given. Zeros without records."""
    values = np.abs(np.asarray(peaks, dtype=float))
    if not len(values):
        return np.zeros(values.shape[1:])
    rule = rule or design_rule(len(values))
    return values.mean(axis=0) if rule == "mean" else values.max(axis=0)


def base_shear_factor(v_static: float, v_history: float, share: float | None = None) -> float:
    """``max(1, share·V / Vth)``: the factor on every response of a suite (1 without either
    base shear)."""
    if v_static <= 0 or v_history <= 0:
        return 1.0
    if share is None:
        found = rules()
        share = found.baseShearShare if found is not None else 1.0
    return max(1.0, share * v_static / v_history)


# ─────────────────────────────────────── records ───────────────────────────────────────


def read_acceleration(path: str | Path, units: str = "g", dt: float | None = None) -> tuple:
    """``(dt, accelerations in g)`` of a record file (PEER .AT2, two columns or one value per
    line, with ``dt`` for the last); ``units`` "g" or "m/s2". Raises ``ValueError`` /
    ``OSError`` when it cannot be read."""
    from opensees_studio.core.ground_motion import detect_format, read_record

    fmt = detect_format(path)
    step, values, _ = read_record(path, fmt, dt=dt)
    accel = np.asarray(values, dtype=float)
    return float(step), accel if units == "g" else accel / G


def ground_acceleration(
    project: dict[str, Any], model_dir: str | Path, series_id: int
) -> tuple[float, np.ndarray] | None:
    """``(dt, ground acceleration in m/s²)`` of a record-backed Path time series of an analysis
    model (its factor applied, as the analysis applies it), or None when it has no record."""
    from opensees_studio.core.ground_motion import read_record

    series = next(
        (s for s in project.get("time_series", []) if int(s.get("id", 0)) == int(series_id)),
        None,
    )
    if series is None or series.get("record_id") is None:
        return None
    record = next(
        (
            r
            for r in project.get("ground_motions", [])
            if int(r.get("id", 0)) == int(series["record_id"])
        ),
        None,
    )
    if record is None:
        return None
    path = Path(model_dir) / record["source_path"]
    try:
        _, values, _ = read_record(path, record["format"], dt=record.get("dt"))
    except (OSError, ValueError):
        return None
    dt = float(series.get("dt") or record.get("dt"))
    return dt, float(series.get("factor", 1.0)) * np.asarray(values, dtype=float)


# ─────────────────────────────────────── spectra ───────────────────────────────────────


def target_spectrum(settings: Any, axes: str = "X", procedure: str = "linear") -> Any:
    """The target spectrum (an OpenSees Studio ``TargetSpectrum`` table, in g) of a suite in
    ``axes`` ("X", "Y" or "XY"): the site's design spectrum with the pack's target R and I of
    the ``procedure`` (empty: the building's own; for "XY" the smaller R of the two
    directions, the larger spectrum), at the pack's spectrum damping. Raises ``ValueError``
    without a seismic zone or rules."""
    from opensees_studio.core.target_spectrum import TargetSpectrum

    from saengine.fem import loads as fl
    from saengine.library.settings import derived

    found = rules()
    if found is None:
        raise ValueError("the code pack in force has no rules for time-history suites")
    values = derived(settings)
    if not values.get("Z"):
        raise ValueError("the site has no seismic zone coefficient Z")
    target = found.targets.get(procedure)
    r = target.R if target is not None and target.R else None
    if r is None:
        r = min(float(values.get(f"R{a}", values["R"]) or values["R"]) for a in axes)
    importance = target.I if target is not None and target.I else values["seismicImportance"]
    periods = np.geomspace(0.01, 10.0, 240)
    sa = [
        fl.design_acceleration(
            float(t),
            settings.site.siteClass,
            float(values["Z"]),
            float(importance),
            float(r),
            found.spectrumDamping,
        )
        for t in periods
    ]
    return TargetSpectrum(
        id=1,
        kind="user",
        periods=[float(t) for t in periods],
        sa=[float(v) for v in sa],
        damping_ratio=found.spectrumDamping,
    )


def _ratio(paired: bool) -> float:
    found = rules()
    if found is None:
        return 1.0
    return float(found.pairRatio if paired else found.singleRatio)


@dataclass
class SuiteCheck:
    """A suite against its target over the period range: the mean spectrum ``mean`` [g] and
    the target ``target`` [g] at ``periods`` [s], ``ratio`` the pack's ratio (single or pair),
    ``least`` the least mean / (ratio·target), at ``governing``; ``shortfall`` the factor that
    meets the criterion (1 when it is met)."""

    period: float
    periods: list[float]
    mean: list[float]
    target: list[float]
    ratio: float
    least: float
    governing: float
    paired: bool
    count: int
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        # 0.1 %: the grid of the derivation and of the check are not the same points.
        return self.least >= 1.0 - TOLERANCE

    @property
    def shortfall(self) -> float:
        return 1.0 if self.ok or self.least <= 0 else 1.0 / self.least

    def as_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "periods": self.periods,
            "mean": self.mean,
            "target": self.target,
            "ratio": self.ratio,
            "least": self.least,
            "governing": self.governing,
            "paired": self.paired,
            "count": self.count,
            "ok": self.ok,
            "shortfall": self.shortfall,
        }


def _members(
    records: Sequence[tuple[float, np.ndarray]],
    pairs: Sequence[tuple[int, int]] | None,
    periods: np.ndarray,
    damping: float,
) -> list[np.ndarray]:
    from opensees_studio.core.response_spectrum import response_spectrum

    spectra = [response_spectrum(dt, acc, damping, periods=periods).sa for dt, acc in records]
    if not pairs:
        return spectra
    return [np.sqrt(spectra[a] ** 2 + spectra[b] ** 2) for a, b in pairs]


def check_suite(
    records: Sequence[tuple[float, np.ndarray]],
    target: Any,
    period: float,
    pairs: Sequence[tuple[int, int]] | None = None,
    points: int = CHECK_POINTS,
) -> SuiteCheck:
    """The suite's (records in g, already scaled; ``pairs``: indices of the two components of
    each pair) mean spectrum against ``ratio``·target over the pack's period range around
    ``period``. Raises ``ValueError`` without rules, records or a period."""
    found = rules()
    if found is None:
        raise ValueError("the code pack in force has no rules for time-history suites")
    if not records or period <= 0:
        raise ValueError("a suite check needs records and a period")
    periods = np.geomspace(found.periodLower * period, found.periodUpper * period, points)
    members = _members(records, pairs, periods, found.spectrumDamping)
    mean = np.mean(members, axis=0)
    goal = np.asarray(target.sa_at(periods), dtype=float)
    ratio = _ratio(bool(pairs))
    share = mean / (ratio * goal)
    k = int(np.argmin(share))
    count = len(members)
    check = SuiteCheck(
        period=float(period),
        periods=[float(t) for t in periods],
        mean=[float(v) for v in mean],
        target=[float(v) for v in goal],
        ratio=ratio,
        least=float(share[k]),
        governing=float(periods[k]),
        paired=bool(pairs),
        count=count,
    )
    if count < found.minimumRecords:
        check.notes.append(
            f"{count} {'pairs' if pairs else 'records'}: the suite needs at least "
            f"{found.minimumRecords} ({clause('records')})"
        )
    return check


def scale_suite(
    records: Sequence[tuple[float, np.ndarray]],
    target: Any,
    period: float,
    pairs: Sequence[tuple[int, int]] | None = None,
    individual: bool = True,
) -> list[float]:
    """The amplitude factor of each record (in g; both components of a pair share one) that
    makes the suite just meet the pack's criterion (:func:`check_suite`): with ``individual``
    each record (or pair) is first fitted to the target over the range in log space, then one
    factor lifts the suite; otherwise one factor on every record. Raises ``ValueError``."""
    from opensees_studio.core.scaling import period_range_scale_factors

    found = rules()
    if found is None:
        raise ValueError("the code pack in force has no rules for time-history suites")
    result = period_range_scale_factors(
        {k: (dt, np.asarray(acc, dtype=float)) for k, (dt, acc) in enumerate(records)},
        target,
        period,
        a=found.periodLower,
        b=found.periodUpper,
        alpha=_ratio(bool(pairs)),
        individual=individual,
        pairs=[tuple(p) for p in pairs] if pairs else None,
        damping=found.spectrumDamping,
        n_periods=CHECK_POINTS,
    )
    return [float(result.factors[k]) for k in range(len(records))]


# ─────────────────────────────────────── the derivation ───────────────────────────────────────


def suite_factors(
    histories: Sequence[Any],
    settings: Any,
    project_dir: str | Path,
    periods: dict[str, float],
    procedure: str = "linear",
    mean_from: int | None = None,
) -> tuple[dict[int, float], list[str]]:
    """The code scale factors (in g, on the record and on its orthogonal component) of the
    ``histories`` scaled to the code spectrum (:func:`scaled_to_code`), suite by suite:
    ``({history index: factor}, notes)``. ``project_dir``: the project folder the record paths
    are relative to; ``periods``: the fundamental period [s] per direction ("X", "Y"), the
    settings' ``analysis.timeHistoryPeriod`` overriding it (pairs: the longer of the two). A
    suite that cannot be scaled keeps its manual factors, with a note. ``procedure``: the
    pack's target ("linear", or "nonlinear" for B36, R = 1 and I = 1); ``mean_from``: the
    procedure's own number of records from which the mean governs (the notes)."""
    out: dict[int, float] = {}
    notes: list[str] = []
    if rules() is None:
        if any(scaled_to_code(h, settings, procedure) for h in histories):
            notes.append(
                "time histories: the code pack in force has no record scaling rules; the "
                "manual factors are used"
            )
        return out, notes
    nonlinear = procedure == "nonlinear"
    label = "nonlinear time-history suite" if nonlinear else "time-history suite"
    spectrum = "real design spectrum (R = 1, I = 1)" if nonlinear else "design spectrum"
    source = clause("nonlinearRecords" if nonlinear else "records") or clause("records")
    analysis = getattr(settings, "analysis", None)
    given = getattr(analysis, "timeHistoryPeriod", None)
    individual = getattr(analysis, "timeHistoryScaling", "individual") == "individual"
    for key, members in suites(histories).items():
        members = [k for k in members if scaled_to_code(histories[k], settings, procedure)]
        if not members:
            continue
        period = given or (
            max(periods.get("X") or 0.0, periods.get("Y") or 0.0)
            if key == "XY"
            else periods.get(key) or 0.0
        )
        try:
            if period <= 0:
                raise ValueError("no fundamental period")
            records: list[tuple[float, np.ndarray]] = []
            pairs: list[tuple[int, int]] = []
            for k in members:
                h = histories[k]
                records.append(read_acceleration(Path(project_dir) / h.record, h.units, h.dt))
                if key == "XY":
                    records.append(
                        read_acceleration(Path(project_dir) / h.recordOrthogonal, h.units, h.dt)
                    )
                    pairs.append((len(records) - 2, len(records) - 1))
            target = target_spectrum(settings, "XY" if key == "XY" else key, procedure)
            factors = scale_suite(records, target, period, pairs or None, individual)
        except (OSError, ValueError, KeyError) as error:
            notes.append(f"{label} {key} not scaled to the code spectrum: {error}")
            continue
        step = 2 if key == "XY" else 1
        for n, k in enumerate(members):
            out[k] = factors[n * step]
        found = rules()
        count = len(members)
        rule = (
            "the largest response"
            if design_rule(count, mean_from) == "max"
            else "the mean response"
        )
        notes.append(
            f"{label} {key}: {count} {'pairs' if key == 'XY' else 'records'} scaled "
            f"to the {spectrum} over {found.periodLower:g}T to {found.periodUpper:g}T, "
            f"T = {period:.3f} s ({source}); design value: {rule}"
        )
        if found is not None and count < found.minimumRecords:
            notes.append(
                f"{label} {key}: {count} {'pairs' if key == 'XY' else 'records'}, "
                f"fewer than the {found.minimumRecords} the code pack asks for "
                f"({source}); the suite is not used in design"
            )
    return out, notes

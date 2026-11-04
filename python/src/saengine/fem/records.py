"""Ground motion records and suites for the response history procedures (B19).

The engine is generic: what a suite must satisfy comes from the code pack in force (its
``seismic.timeHistory`` rules, :class:`saengine.codes.tables.TimeHistoryRules`), and the
spectra and the period-range scaling are OpenSees Studio's (:mod:`opensees_studio.core.
response_spectrum`, :mod:`opensees_studio.core.scaling`), not a copy of them.

- **Suites.** The time histories of a project form one suite per direction ("X", "Y": one
  horizontal record each, a two-dimensional suite) and one of pairs ("XY": a record with its
  orthogonal component, applied simultaneously, a three-dimensional suite). A suite needs the
  pack's ``minimumRecords`` (the default pack's Part 6 Sec 2.5.10.2: at least three).
- **Scaling** (``method`` "periodRange"): at every period from ``periodLower``·T to
  ``periodUpper``·T the mean of the records' ``spectrumDamping``-damped spectra (of a pair, the
  SRSS of its two components, one factor on both) is not below ``singleRatio`` (pairs:
  ``pairRatio``) times the target spectrum. The target is the design spectrum of the site
  (``targets.linear``: the building's own R and I) or, for the nonlinear procedure, the one
  with the pack's R and I (``targets.nonlinear``; the default pack's Sec 2.5.11.2: R = 1, I = 1). T is the
  fundamental period of the direction (of the structure for pairs).
- **Design value** (:func:`design_value`): the largest of the records' peaks below ``meanFrom``
  records (or pairs), their mean from it (the default pack's Sec 2.5.10.3: seven).
- **Base shear** (:func:`base_shear_factor`): where the suite's base shear Vth is below
  ``baseShearShare``·V (V the equivalent static base shear), every response times
  share·V/Vth (the default pack's Sec 2.5.10.3).
- **P5, by the pack.** A procedure's ``targets`` entry may give its own least number of
  records, period range, ratios and a factor on the spectrum (:func:`value`); a pair's
  spectrum is the SRSS, the maximum-direction spectrum or each component's
  (``pairCombination``); a pair's range may run from the shorter to the longer period
  (``periodBasis`` "bounds", :func:`period_range`); the records may be spectrally matched in
  place of scaled (:func:`modification`, the pack's ``matching`` method, the project may choose
  either), the matched suite then checked against ``matchedRatio``.

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


# ── P5: the procedure's own values (its ``targets`` entry over the table's) ──

#: The values a procedure's ``targets`` entry may give in place of the table's.
PROCEDURE_VALUES = (
    "minimumRecords",
    "periodLower",
    "periodUpper",
    "periodBasis",
    "singleRatio",
    "pairRatio",
    "matchedRatio",
)


def value(name: str, procedure: str | None = None) -> Any:
    """The pack's ``name`` of the time-history rules for ``procedure`` ("linear",
    "nonlinear", ...): its ``targets`` entry's when it gives one, else the table's (None
    without rules)."""
    found = rules()
    if found is None:
        return None
    target = found.targets.get(procedure) if procedure else None
    own = getattr(target, name, None) if target is not None else None
    return own if own is not None else getattr(found, name, None)


def modification(settings: Any, procedure: str = "linear") -> str:
    """How the records of ``procedure`` are modified to the target: "amplitude" (scaled over
    the period range) or "matching" (spectrally matched): the project's ``analysis.
    timeHistoryModification`` unless "pack", else the pack's for the procedure; "amplitude"
    when the pack gives no matching method."""
    found = rules()
    if found is None:
        return "amplitude"
    chosen = getattr(getattr(settings, "analysis", None), "timeHistoryModification", "pack")
    if chosen not in ("amplitude", "matching"):
        target = found.targets.get(procedure)
        chosen = target.modification if target is not None else "amplitude"
    return (
        "matching"
        if chosen == "matching" and matching_rule(settings) is not None
        else ("amplitude")
    )


def matching_rule(settings: Any = None) -> Any | None:
    """The pack's spectral matching rule, with the project's method when it names one
    (``analysis.timeHistoryMatching``); None when neither gives a method."""
    found = rules()
    if found is None:
        return None
    rule = found.matching
    method = getattr(getattr(settings, "analysis", None), "timeHistoryMatching", "pack")
    if method in (None, "pack"):
        return rule
    if rule is None:
        from saengine.codes.tables import SpectralMatching

        return SpectralMatching(method=method)
    return rule.model_copy(update={"method": method})


def period_range(
    key: str, periods: dict[str, float], given: float | None, procedure: str | None = None
) -> tuple[float, float, float]:
    """``(low, high, T)`` [s]: the period range of a suite in ``key`` ("X", "Y", "XY") and its
    period T: ``given`` (the settings' period), else the direction's fundamental period (a
    pair: the longer of the two); with the pack's ``periodBasis`` "bounds" a pair's range runs
    from periodLower × the shorter to periodUpper × the longer. Zeros without a period."""
    lower, upper = value("periodLower", procedure), value("periodUpper", procedure)
    tx, ty = periods.get("X") or 0.0, periods.get("Y") or 0.0
    if key == "XY":
        period = given or max(tx, ty)
        shortest = given or (min(t for t in (tx, ty) if t > 0) if tx > 0 or ty > 0 else 0.0)
    else:
        period = given or periods.get(key) or 0.0
        shortest = period
    if not period or lower is None or upper is None:
        return 0.0, 0.0, 0.0
    if value("periodBasis", procedure) == "bounds":
        return float(lower) * float(shortest), float(upper) * float(period), float(period)
    return float(lower) * float(period), float(upper) * float(period), float(period)


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
    # P5: the target as a multiple of the design spectrum (e.g. the maximum considered
    # earthquake); 1 for the default pack.
    factor = float(target.factor) if target is not None else 1.0
    periods = np.geomspace(0.01, 10.0, 240)
    seismic = code_context.table("seismic")
    shape = getattr(seismic, "designSpectrum", None)
    if (
        target is not None
        and target.spectrum == "elastic"
        and shape is not None
        and shape.method == "behaviourFactor"
    ):
        # P5: the elastic response spectrum of the behaviour-factor shape, ag = Z·I.
        from saengine.fem.spectra import elastic_spectrum

        site = seismic.siteClasses[settings.site.siteClass]
        ag = float(values["Z"]) * float(importance)
        sa = [
            factor
            * elastic_spectrum(float(t), ag, site.S, site.TB, site.TC, site.TD, shape.plateau)
            for t in periods
        ]
    else:
        sa = [
            factor
            * fl.design_acceleration(
                float(t),
                settings.site.siteClass,
                values["Z"],  # a float; C1: the mapped values kept
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


def _ratio(paired: bool, procedure: str | None = None, matched: bool = False) -> float:
    found = rules()
    if found is None:
        return 1.0
    if matched:
        own = value("matchedRatio", procedure)
        if own is not None:
            return float(own)
    return float(value("pairRatio" if paired else "singleRatio", procedure))


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

    found = rules()
    combination = found.pairCombination if found is not None else "srss"
    if pairs and combination != "srss":
        # P5: the maximum-direction spectrum, or each component's own (fem.spectral_matching).
        from saengine.fem.spectral_matching import pair_spectrum

        return [
            pair_spectrum(records[a], records[b], periods, damping, combination) for a, b in pairs
        ]
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
    procedure: str | None = None,
    bounds: tuple[float, float] | None = None,
    matched: bool = False,
) -> SuiteCheck:
    """The suite's (records in g, already scaled; ``pairs``: indices of the two components of
    each pair) mean spectrum against ``ratio``·target over the pack's period range around
    ``period`` (``bounds``: the range [s] itself, :func:`period_range`), with the values of
    ``procedure`` and, for ``matched`` records, the pack's matched ratio. Raises
    ``ValueError`` without rules, records or a period."""
    found = rules()
    if found is None:
        raise ValueError("the code pack in force has no rules for time-history suites")
    if not records or period <= 0:
        raise ValueError("a suite check needs records and a period")
    if bounds is not None:
        periods = np.geomspace(bounds[0], bounds[1], points)
    else:
        periods = np.geomspace(found.periodLower * period, found.periodUpper * period, points)
    members = _members(records, pairs, periods, found.spectrumDamping)
    mean = np.mean(members, axis=0)
    goal = np.asarray(target.sa_at(periods), dtype=float)
    ratio = _ratio(bool(pairs), procedure, matched)
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
    least = int(value("minimumRecords", procedure) or found.minimumRecords)
    if count < least:
        check.notes.append(
            f"{count} {'pairs' if pairs else 'records'}: the suite needs at least "
            f"{least} ({clause('records')})"
        )
    return check


def scale_suite(
    records: Sequence[tuple[float, np.ndarray]],
    target: Any,
    period: float,
    pairs: Sequence[tuple[int, int]] | None = None,
    individual: bool = True,
    procedure: str | None = None,
    bounds: tuple[float, float] | None = None,
) -> list[float]:
    """The amplitude factor of each record (in g; both components of a pair share one) that
    makes the suite just meet the pack's criterion (:func:`check_suite`): with ``individual``
    each record (or pair) is first fitted to the target over the range in log space, then one
    factor lifts the suite; otherwise one factor on every record. ``procedure``, ``bounds``: as
    for :func:`check_suite`. Raises ``ValueError``."""
    from opensees_studio.core.scaling import period_range_scale_factors

    found = rules()
    if found is None:
        raise ValueError("the code pack in force has no rules for time-history suites")
    alpha = _ratio(bool(pairs), procedure)
    if bounds is None and procedure is not None:
        low, high = value("periodLower", procedure), value("periodUpper", procedure)
        if (low, high) != (found.periodLower, found.periodUpper):
            bounds = (float(low) * period, float(high) * period)
    if pairs and found.pairCombination != "srss":
        return _scale_members(records, target, period, pairs, individual, alpha, bounds)
    a, b, t1 = (found.periodLower, found.periodUpper, period)
    if bounds is not None:
        a, b, t1 = bounds[0], bounds[1], 1.0
    result = period_range_scale_factors(
        {k: (dt, np.asarray(acc, dtype=float)) for k, (dt, acc) in enumerate(records)},
        target,
        t1,
        a=a,
        b=b,
        alpha=alpha,
        individual=individual,
        pairs=[tuple(p) for p in pairs] if pairs else None,
        damping=found.spectrumDamping,
        n_periods=CHECK_POINTS,
    )
    return [float(result.factors[k]) for k in range(len(records))]


def _scale_members(
    records: Sequence[tuple[float, np.ndarray]],
    target: Any,
    period: float,
    pairs: Sequence[tuple[int, int]],
    individual: bool,
    alpha: float,
    bounds: tuple[float, float] | None,
) -> list[float]:
    """:func:`scale_suite` of pairs combined by the pack's ``pairCombination`` other than the
    SRSS (the same method as OpenSees Studio's period-range scaling: each pair fitted in log
    space when ``individual``, then one factor so that the least mean / (alpha·target) over the
    range is 1). The combined spectra are linear in a common factor on both components."""
    found = rules()
    low, high = (
        bounds
        if bounds is not None
        else (
            found.periodLower * period,
            found.periodUpper * period,
        )
    )
    periods = np.geomspace(low, high, CHECK_POINTS)
    goal = np.asarray(target.sa_at(periods), dtype=float)
    if np.any(goal <= 0):
        raise ValueError("The target spectrum is zero somewhere in the range.")
    members = _members(records, pairs, periods, found.spectrumDamping)
    for k, sa in enumerate(members):
        if np.any(sa <= 0):
            raise ValueError(f"pair {k + 1} has a zero spectral ordinate in the range.")
    fit = (
        [float(np.exp(np.mean(np.log(goal / sa)))) for sa in members]
        if individual
        else [1.0] * len(members)
    )
    mean = np.mean([f * sa for f, sa in zip(fit, members, strict=True)], axis=0)
    lift = 1.0 / float(np.min(mean / (alpha * goal)))
    factors = [0.0] * len(records)
    for f, (a, b) in zip(fit, pairs, strict=True):
        factors[a] = factors[b] = f * lift
    return factors


def _spectrum_label(procedure: str) -> str:
    """The target spectrum of ``procedure`` in a note."""
    found = rules()
    target = found.targets.get(procedure) if found is not None else None
    if procedure != "nonlinear" or target is None:
        return "design spectrum"
    if (target.R, target.I, target.factor) == (1.0, 1.0, 1.0):
        return "real design spectrum (R = 1, I = 1)"
    parts = [f"R = {target.R:g}" if target.R else "the building's R"]
    parts.append(f"I = {target.I:g}" if target.I else "the building's I")
    times = f"{target.factor:g} × " if target.factor != 1.0 else ""
    return f"target spectrum ({times}the design spectrum with {', '.join(parts)})"


# ─────────────────────────────────────── the derivation ───────────────────────────────────────

#: P5: the folder (beside the analysis model) of the spectrally matched records.
MATCHED_FOLDER = "matched-records"


def suite_factors(
    histories: Sequence[Any],
    settings: Any,
    project_dir: str | Path,
    periods: dict[str, float],
    procedure: str = "linear",
    mean_from: int | None = None,
    matched_dir: str | Path | None = None,
    matched: dict[int, tuple[str, str | None]] | None = None,
) -> tuple[dict[int, float], list[str]]:
    """The code scale factors (in g, on the record and on its orthogonal component) of the
    ``histories`` scaled to the code spectrum (:func:`scaled_to_code`), suite by suite:
    ``({history index: factor}, notes)``. ``project_dir``: the project folder the record paths
    are relative to; ``periods``: the fundamental period [s] per direction ("X", "Y"), the
    settings' ``analysis.timeHistoryPeriod`` overriding it (pairs: the longer of the two). A
    suite that cannot be scaled keeps its manual factors, with a note. ``procedure``: the
    pack's target ("linear", or "nonlinear" for B36, R = 1 and I = 1); ``mean_from``: the
    procedure's own number of records from which the mean governs (the notes).

    P5: where the records of the procedure are spectrally matched (:func:`modification`) and
    ``matched_dir`` (a folder beside the model) and ``matched`` (filled here) are given, each
    record is matched to the target (:mod:`saengine.fem.spectral_matching`), written there,
    and ``matched[index]`` holds the paths (relative to ``project_dir``) of the matched record
    and its orthogonal component; the factor is then the one that lifts the matched suite to
    the pack's matched criterion (1 when it is met)."""
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
    spectrum = _spectrum_label(procedure)
    source = clause("nonlinearRecords" if nonlinear else "records") or clause("records")
    analysis = getattr(settings, "analysis", None)
    given = getattr(analysis, "timeHistoryPeriod", None)
    individual = getattr(analysis, "timeHistoryScaling", "individual") == "individual"
    matching = (
        modification(settings, procedure) == "matching"
        and matched_dir is not None
        and matched is not None
    )
    least = int(value("minimumRecords", procedure) or rules().minimumRecords)
    for key, members in suites(histories).items():
        members = [k for k in members if scaled_to_code(histories[k], settings, procedure)]
        if not members:
            continue
        low, high, period = period_range(key, periods, given, procedure)
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
            bounds = (low, high) if value("periodBasis", procedure) == "bounds" else None
            if matching:
                found_matched, factors, more = _match_suite(
                    [histories[k] for k in members],
                    records,
                    pairs or None,
                    target,
                    period,
                    (low, high),
                    procedure,
                    Path(project_dir),
                    Path(matched_dir),
                    settings,
                )
                notes += [f"{label} {key}: {text}" for text in more]
            else:
                factors = scale_suite(
                    records, target, period, pairs or None, individual, procedure, bounds
                )
        except (OSError, ValueError, KeyError) as error:
            notes.append(f"{label} {key} not scaled to the code spectrum: {error}")
            continue
        step = 2 if key == "XY" else 1
        for n, k in enumerate(members):
            out[k] = factors[n * step]
            if matching:
                matched[k] = found_matched[n]
        found = rules()
        count = len(members)
        rule = (
            "the largest response"
            if design_rule(count, mean_from) == "max"
            else "the mean response"
        )
        lower, upper = value("periodLower", procedure), value("periodUpper", procedure)
        if value("periodBasis", procedure) == "bounds" and key == "XY":
            span = f"{low:.3f} s to {high:.3f} s ({lower:g}Tmin to {upper:g}Tmax)"
        else:
            span = f"{lower:g}T to {upper:g}T"
        notes.append(
            f"{label} {key}: {count} {'pairs' if key == 'XY' else 'records'} "
            f"{'spectrally matched' if matching else 'scaled'} "
            f"to the {spectrum} over {span}, "
            f"T = {period:.3f} s ({source}); design value: {rule}"
        )
        if found is not None and count < least:
            notes.append(
                f"{label} {key}: {count} {'pairs' if key == 'XY' else 'records'}, "
                f"fewer than the {least} the code pack asks for "
                f"({source}); the suite is not used in design"
            )
    return out, notes


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:40] or "record"


def _match_suite(
    histories: Sequence[Any],
    records: list[tuple[float, np.ndarray]],
    pairs: list[tuple[int, int]] | None,
    target: Any,
    period: float,
    bounds: tuple[float, float],
    procedure: str,
    project_dir: Path,
    matched_dir: Path,
    settings: Any,
) -> tuple[list[tuple[str, str | None]], list[float], list[str]]:
    """Every record (each component of a pair) of a suite matched to the target times the
    share of the procedure's matched criterion a component must meet
    (:func:`saengine.fem.spectral_matching.component_share`), written as two columns (t [s],
    a [g]) with its matching summary beside it (``.json``) in ``matched_dir``, kept while the
    inputs are the same; then the one factor that lifts the matched suite to the criterion
    (never below 1). Returns the paths per history, the factor per record and the notes."""
    import hashlib
    import json

    from saengine.fem import spectral_matching as sm

    found = rules()
    rule = matching_rule(settings)
    if rule is None:
        raise ValueError("the code pack gives no spectral matching method")
    paired = bool(pairs)
    ratio = _ratio(paired, procedure, matched=True)
    share = sm.component_share(found.pairCombination) if paired else 1.0
    low, high = bounds

    def goal(periods: np.ndarray) -> np.ndarray:
        return ratio * share * np.asarray(target.sa_at(periods), dtype=float)

    matched_dir.mkdir(parents=True, exist_ok=True)
    out_records: list[tuple[float, np.ndarray]] = []
    paths: list[str] = []
    notes: list[str] = []
    worst = 0.0
    for k, (dt, acc) in enumerate(records):
        history = histories[k // 2 if paired else k]
        part = k % 2 if paired else 0
        key = hashlib.sha1(
            json.dumps(
                [
                    hashlib.sha1(np.asarray(acc, dtype=float).tobytes()).hexdigest(),
                    float(dt),
                    [float(v) for v in goal(np.geomspace(low, high, 12))],
                    float(low),
                    float(high),
                    rule.model_dump(mode="json"),
                    float(found.spectrumDamping),
                ]
            ).encode()
        ).hexdigest()[:10]
        stem = f"{_safe(history.name)}-{procedure}-{part}-{key}"
        path = matched_dir / f"{stem}.txt"
        summary_path = matched_dir / f"{stem}.json"
        if path.is_file() and summary_path.is_file():
            step, values = read_acceleration(path, "g")
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        else:
            result = sm.match(dt, acc, goal, low, high, rule, found.spectrumDamping)
            step, values = result.dt, result.accel
            t = np.arange(values.size) * step
            path.write_text(
                "\n".join(f"{ti:.9f} {ai:.9e}" for ti, ai in zip(t, values, strict=True)) + "\n",
                encoding="utf-8",
            )
            summary = {
                "timeHistory": history.name,
                "component": part,
                "procedure": procedure,
                "file": path.name,
                **result.summary(),
            }
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
        worst = max(worst, float(summary.get("misfit", 0.0)))
        if not summary.get("converged"):
            notes.append(
                f"{history.name}: matched within {100 * float(summary['misfit']):.0f} % of the "
                f"target after {summary['iterations']} iterations (the pack's tolerance "
                f"{100 * rule.tolerance:.0f} %)"
            )
        out_records.append((float(step), np.asarray(values, dtype=float)))
        paths.append(Path(path).resolve().relative_to(project_dir.resolve()).as_posix())
    check = check_suite(
        out_records, target, period, pairs, procedure=procedure, bounds=bounds, matched=True
    )
    lift = check.shortfall
    factors = [lift] * len(records)
    per_history = (
        [(paths[2 * n], paths[2 * n + 1]) for n in range(len(histories))]
        if paired
        else [(p, None) for p in paths]
    )
    notes.append(
        f"{len(records)} record{'s' if len(records) != 1 else ''} matched by "
        f"'{rule.method}' within {100 * worst:.0f} % of {ratio * share:g} × the target "
        f"({low:.3f} s to {high:.3f} s); "
        + (
            f"the suite is lifted by {lift:.3f} to meet {ratio:g} × the target"
            if lift > 1.0
            else f"the suite meets {ratio:g} × the target"
        )
    )
    return per_history, factors, notes

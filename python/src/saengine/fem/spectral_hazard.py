"""The seismic hazard of a site from mapped spectral values (method ``mappedSpectral``).

A code pack chooses how the design spectrum is found with its ``seismic.designSpectrum.method``
(:class:`saengine.codes.tables.DesignSpectrumRule`; C4 adds ``behaviourFactor``,
:mod:`saengine.fem.spectra`):

- ``reducedElastic`` (the default, and the default pack's): a zone coefficient Z and the site class's
  S, TB, TC, TD (:func:`saengine.fem.loads.normalized_spectrum`); nothing here is used;
- ``mappedSpectral``: the site's design spectral accelerations SDS and SD1 (with S1 and the
  long-period transition TL) from the code authority's hazard maps or tool, entered in Project
  Settings > Site (``site.spectral``), or its multi-period spectrum. This module computes from them
  the two-period design spectrum, the equivalent lateral force coefficient Cs with its bounds,
  the band of the Seismic Design Category table, and the period's upper limit Cu·Ta. Every
  number comes from the pack's ``designSpectrum`` block.

The site's values travel through the program as the derived "Z" (:func:`saengine.library.settings.derived`):
a :class:`SpectralHazard`, a float equal to SDS (so the code that asks "is there a seismic
hazard" and scales by it keeps working) that carries SD1, S1, TL and the multi-period spectrum.
:func:`saengine.fem.loads.design_acceleration` and the other readers look for it.

Units: g, s.
"""

from __future__ import annotations

from itertools import pairwise
from types import SimpleNamespace
from typing import Any, Self

from saengine.codes import context as code_context

METHOD = "mappedSpectral"


class SpectralHazard(float):
    """SDS [g] (the float value) with the site's other mapped values: ``sd1``, ``s1``, ``tl``
    [s] (None: not given) and ``spectrum`` (the site's multi-period design spectrum, (T, Sa)
    points, or None) and where the values come from (``source``)."""

    sd1: float
    s1: float | None
    tl: float | None
    spectrum: tuple[tuple[float, float], ...] | None
    source: str

    def __new__(
        cls,
        sds: float,
        sd1: float,
        s1: float | None = None,
        tl: float | None = None,
        spectrum: Any = None,
        source: str = "",
    ) -> Self:
        obj = super().__new__(cls, float(sds))
        obj.sd1 = float(sd1)
        obj.s1 = None if s1 is None else float(s1)
        obj.tl = None if tl is None else float(tl)
        obj.spectrum = (
            tuple(sorted((float(t), float(a)) for t, a in spectrum)) if spectrum else None
        )
        obj.source = source
        return obj

    def __reduce__(self) -> Any:  # picklable (multiprocessing of the design)
        return (
            SpectralHazard,
            (float(self), self.sd1, self.s1, self.tl, self.spectrum, self.source),
        )

    @property
    def sds(self) -> float:
        return float(self)

    @property
    def ts(self) -> float:
        """TS = SD1 / SDS [s]."""
        return self.sd1 / float(self) if float(self) > 0 else 0.0


def rule(pack: Any = None) -> Any:
    """The pack's ``seismic.designSpectrum`` block when its method is ``mappedSpectral``, else
    None."""
    table = pack.table("seismic") if pack is not None else code_context.table("seismic")
    hazard = getattr(table, "designSpectrum", None)
    return hazard if hazard is not None and hazard.method == METHOD else None


def uses_mapped(pack: Any = None) -> bool:
    """Whether the pack (default: the pack in force) finds the spectrum from mapped values."""
    return rule(pack) is not None


def _interp(points: list[tuple[float, float]] | tuple[tuple[float, float], ...], x: float) -> float:
    pts = list(points)
    if x <= pts[0][0]:
        return float(pts[0][1])
    for (x0, y0), (x1, y1) in pairwise(pts):
        if x <= x1:
            return float(y0 + (y1 - y0) * (x - x0) / (x1 - x0)) if x1 > x0 else float(y1)
    return float(pts[-1][1])


def from_mcer(spectrum: Any, site_class: str, pack: Any = None) -> tuple[float, float]:
    """(SDS, SD1) from a multi-period MCER spectrum ((T, Sa) points) by the pack's
    ``hazard.multiPeriod`` rule; ValueError when the pack has none."""
    hazard = rule(pack)
    if hazard is None or hazard.multiPeriod is None or hazard.designShare is None:
        raise ValueError("the code pack gives no rule for SMS and SM1 from a multi-period spectrum")
    mp = hazard.multiPeriod
    pts = sorted((float(t), float(a)) for t, a in spectrum)
    lo, hi = mp.smsPeriods
    in_range = [a for t, a in pts if lo - 1e-9 <= t <= hi + 1e-9]
    sms = mp.smsShare * max(in_range or [_interp(pts, lo)])
    lo1, hi1 = (
        mp.sm1PeriodsSoft
        if mp.sm1PeriodsSoft is not None and site_class in mp.softClasses
        else mp.sm1Periods
    )
    products = [t * a for t, a in pts if lo1 - 1e-9 <= t <= hi1 + 1e-9]
    sm1 = max(products or [lo1 * _interp(pts, lo1)])
    return hazard.designShare * sms, hazard.designShare * sm1


def site_hazard(spectral: Any, site_class: str, pack: Any = None) -> SpectralHazard | None:
    """The site's :class:`SpectralHazard` from the settings' ``site.spectral`` block (SDS and
    SD1 entered; else from SMS and SM1 with the pack's design share; else from the MCER
    multi-period spectrum); None without values or when the pack's method is not mapped."""
    hazard = rule(pack)
    if hazard is None or spectral is None:
        return None

    def get(name: str) -> float | None:
        value = getattr(spectral, name, None)
        return None if value is None else float(value)

    sds, sd1 = get("sds"), get("sd1")
    source = "entered SDS, SD1"
    share = hazard.designShare
    if (sds is None or sd1 is None) and share is not None:
        sms, sm1 = get("sms"), get("sm1")
        if sms is not None and sm1 is not None:
            sds, sd1, source = share * sms, share * sm1, "SDS, SD1 = (2/3) SMS, SM1"
    coefficients = getattr(hazard, "siteCoefficients", None)  # Alpha 9 C23: Fa SS, Fv S1
    ss, s1 = get("ss"), get("s1")
    missing = sds is None or sd1 is None
    if missing and coefficients is not None and share and ss is not None and s1 is not None:
        factors = site_factors(ss, s1, site_class, pack)
        if factors is not None:
            fa, fv, used = factors
            sds, sd1 = share * fa * ss, share * fv * s1
            source = (
                f"SDS, SD1 = {share:.3g} × Fa SS, Fv S1 with Fa = {fa:.3g}, Fv = {fv:.3g} "
                f"(site class {used})"
            )
    mcer = getattr(spectral, "mcerSpectrum", None)
    if (sds is None or sd1 is None) and mcer:
        try:
            sds, sd1 = from_mcer(mcer, site_class, pack)
            source = "SDS, SD1 from the multi-period MCER spectrum"
        except ValueError:
            pass
    if sds is None or sd1 is None or sds <= 0:
        return None
    design = getattr(spectral, "designSpectrum", None) or None
    return SpectralHazard(sds, sd1, get("s1"), get("tl"), design, source)


def _along(points: list[float], values: list[float], x: float) -> float:
    return _interp(list(zip(points, values, strict=True)), x)


def site_factors(
    ss: float, s1: float, site_class: str, pack: Any = None
) -> tuple[float, float, str] | None:
    """Alpha 9 C23: (Fa, Fv, the class used) of the pack's ``siteCoefficients`` at the mapped
    SS and S1 for ``site_class`` (a class needing a site study, ``siteSpecificStudy``, read as
    its assumed class); None without the table or the class."""
    hazard = rule(pack)
    table = getattr(hazard, "siteCoefficients", None) if hazard is not None else None
    if table is None:
        return None
    used = site_class
    if used not in table.fa.classes or used not in table.fv.classes:
        seismic = pack.table("seismic") if pack is not None else code_context.table("seismic")
        study = getattr(seismic, "siteSpecificStudy", None)
        if study is None or site_class not in study.classes:
            return None
        used = study.assumedClass or ""
        if used not in table.fa.classes or used not in table.fv.classes:
            return None
    fa = _along(list(table.fa.points), list(table.fa.classes[used]), ss)
    fv = _along(list(table.fv.points), list(table.fv.classes[used]), s1)
    return fa, fv, used


def with_location(spectral: Any, location: Any) -> Any:
    """Alpha 9 C23: the site's mapped values with the town's (``locations`` SS, S1, TL) where
    the project gives none; ``spectral`` itself when the town has none."""
    names = ("ss", "s1", "tl")
    town = {n: getattr(location, n, None) for n in names} if location is not None else {}
    if not any(v is not None for v in town.values()):
        return spectral
    if spectral is None:
        merged: dict[str, Any] = {}
    elif hasattr(spectral, "model_dump"):
        merged = spectral.model_dump()
    else:
        merged = dict(vars(spectral))
    for name in names:
        if merged.get(name) is None and town.get(name) is not None:
            merged[name] = town[name]
    return SimpleNamespace(**merged)


def two_period(period: float, hazard: SpectralHazard, pack: Any = None) -> float:
    """The design spectral acceleration Sa [g] of the two-period spectrum (5 % damped) at
    ``period``: from ``rampStart``·SDS at T = 0 up to SDS at T0, SDS to TS, SD1/T to TL,
    SD1·TL/T² beyond."""
    h = rule(pack)
    sds, sd1 = float(hazard), hazard.sd1
    ts = hazard.ts
    t0 = (h.t0Share if h is not None and h.t0Share is not None else 0.2) * ts
    start = h.rampStart if h is not None and h.rampStart is not None else 0.4
    if period < t0 and t0 > 0:
        return sds * (start + (1 - start) * period / t0)
    if period <= ts:
        return sds
    if hazard.tl is None or period <= hazard.tl:
        return sd1 / period
    return sd1 * hazard.tl / period**2


def spectral_acceleration(period: float, hazard: SpectralHazard, pack: Any = None) -> float:
    """Sa [g] at ``period``: the site's multi-period design spectrum where given (linear
    between its points, held at its ends), else the two-period spectrum."""
    if hazard.spectrum:
        return _interp(hazard.spectrum, period)
    return two_period(period, hazard, pack)


def response_coefficient(
    period: float, hazard: SpectralHazard, importance: float, r: float, pack: Any = None
) -> float:
    """The equivalent lateral force coefficient Cs = SDS/(R/Ie), at most SD1/(T R/Ie) up to TL
    and SD1·TL/(T² R/Ie) beyond, at least the pack's ``csLimits``."""
    h = rule(pack)
    ratio = r / importance
    sds, sd1 = float(hazard), hazard.sd1
    cs = sds / ratio
    if period > 0:
        if hazard.tl is None or period <= hazard.tl:
            cs = min(cs, sd1 / (period * ratio))
        else:
            cs = min(cs, sd1 * hazard.tl / (period**2 * ratio))
    limits = h.csLimits if h is not None else None
    if limits is not None:
        cs = max(cs, limits.sdsFactor * sds * importance, limits.floor)
        s1 = hazard.s1
        if (
            s1 is not None
            and limits.nearFaultS1 is not None
            and limits.nearFaultFactor is not None
            and s1 >= limits.nearFaultS1
        ):
            cs = max(cs, limits.nearFaultFactor * s1 / ratio)
    return cs


def band(hazard: SpectralHazard, pack: Any = None) -> int | None:
    """The band (1, 2, ...) of the Seismic Design Category table: the more severe of the bands
    of SDS and SD1 (a band starts at each value of ``sdsBands`` / ``sd1Bands``), the band after
    the last where S1 ≥ ``s1Extreme``. The pack's ``designCategories`` lists one category per
    band, as the zone-based packs list one per zone."""
    h = rule(pack)
    if h is None:
        return None

    def of(value: float, starts: list[float]) -> int:
        return 1 + sum(1 for s in starts if value >= s - 1e-12)

    worst = max(of(float(hazard), list(h.sdsBands)), of(hazard.sd1, list(h.sd1Bands)))
    if h.s1Extreme is not None and hazard.s1 is not None and hazard.s1 >= h.s1Extreme:
        worst = max(len(h.sdsBands), len(h.sd1Bands)) + 2
    return worst


def period_upper_factor(hazard: Any, pack: Any = None) -> float | None:
    """Cu of T ≤ Cu·Ta for the site's SD1 (the pack's ``periodUpper`` points, held beyond
    them); None when the pack has no such table (its ``periodUpperFactor`` applies)."""
    h = rule(pack)
    if h is None or not h.periodUpper or not isinstance(hazard, SpectralHazard):
        return None
    pts = sorted((float(a), float(b)) for a, b in h.periodUpper)
    return _interp(pts, hazard.sd1)


def describe(hazard: SpectralHazard) -> str:
    """The site's values in words, for the notes and the report."""
    parts = [f"SDS = {float(hazard):.3f} g", f"SD1 = {hazard.sd1:.3f} g"]
    if hazard.s1 is not None:
        parts.append(f"S1 = {hazard.s1:.3f} g")
    if hazard.tl is not None:
        parts.append(f"TL = {hazard.tl:g} s")
    text = ", ".join(parts)
    if hazard.spectrum:
        text += f"; multi-period design spectrum of {len(hazard.spectrum)} points"
    return f"{text} ({hazard.source})" if hazard.source else text

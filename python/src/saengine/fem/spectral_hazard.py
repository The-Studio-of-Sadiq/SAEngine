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
  number comes from the pack's ``designSpectrum`` block (alpha 9 C23: with its
  ``siteCoefficients`` also from SS and S1, a town's where the project gives none);
- ``ubc97`` (alpha 9 C16): the seismic coefficients Ca and Cv of the zone's Z and the soil
  profile (with the near-source factors Na, Nv) give the same two-period spectrum with 2.5 Ca in
  place of SDS and Cv in place of SD1 (UBC 1997 Figure 16-3, Sec 1630.2.1); the town's zone
  reads the category table.

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
UBC97 = "ubc97"  # Alpha 9 C16
METHODS = (METHOD, UBC97)


class SpectralHazard(float):
    """SDS [g] (the float value) with the site's other mapped values: ``sd1``, ``s1``, ``tl``
    [s] (None: not given) and ``spectrum`` (the site's multi-period design spectrum, (T, Sa)
    points, or None) and where the values come from (``source``)."""

    sd1: float
    s1: float | None
    tl: float | None
    spectrum: tuple[tuple[float, float], ...] | None
    source: str
    # Alpha 9 C16 (ubc97): the zone that reads the category table, the coefficients for the
    # notes ((name, value) pairs), the least V / W·R/I near the source, the Z of the period cap
    # and what the values are called in the notes and the report.
    zone: int | None
    terms: tuple[tuple[str, Any], ...]
    nearFloor: float | None
    zValue: float | None
    label: str

    def __new__(
        cls,
        sds: float,
        sd1: float,
        s1: float | None = None,
        tl: float | None = None,
        spectrum: Any = None,
        source: str = "",
        zone: int | None = None,
        terms: Any = (),
        nearFloor: float | None = None,
        zValue: float | None = None,
        label: str = "mapped spectral values",
    ) -> Self:
        obj = super().__new__(cls, float(sds))
        obj.sd1 = float(sd1)
        obj.s1 = None if s1 is None else float(s1)
        obj.tl = None if tl is None else float(tl)
        obj.spectrum = (
            tuple(sorted((float(t), float(a)) for t, a in spectrum)) if spectrum else None
        )
        obj.source = source
        obj.zone = zone
        obj.terms = tuple((str(n), v) for n, v in terms)
        obj.nearFloor = None if nearFloor is None else float(nearFloor)
        obj.zValue = None if zValue is None else float(zValue)
        obj.label = label
        return obj

    def __reduce__(self) -> Any:  # picklable (multiprocessing of the design)
        return (
            SpectralHazard,
            (
                float(self),
                self.sd1,
                self.s1,
                self.tl,
                self.spectrum,
                self.source,
                self.zone,
                self.terms,
                self.nearFloor,
                self.zValue,
                self.label,
            ),
        )

    @property
    def sds(self) -> float:
        return float(self)

    @property
    def ts(self) -> float:
        """TS = SD1 / SDS [s]."""
        return self.sd1 / float(self) if float(self) > 0 else 0.0


def rule(pack: Any = None) -> Any:
    """The pack's ``seismic.designSpectrum`` block when its method is ``mappedSpectral`` (or,
    alpha 9 C16, ``ubc97``, which draws the same two-period spectrum), else None."""
    table = pack.table("seismic") if pack is not None else code_context.table("seismic")
    hazard = getattr(table, "designSpectrum", None)
    return hazard if hazard is not None and hazard.method in METHODS else None


def uses_mapped(pack: Any = None) -> bool:
    """Whether the pack (default: the pack in force) draws the two-period spectrum of this
    module (``mappedSpectral`` or ``ubc97``)."""
    return rule(pack) is not None


def takes_mapped_values(pack: Any = None) -> bool:
    """Alpha 9 C16: whether the pack's spectrum needs the site's mapped values
    (``mappedSpectral``); ``ubc97`` takes a zone's Z like the zone packs."""
    h = rule(pack)
    return h is not None and h.method == METHOD


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


def site_hazard(
    spectral: Any,
    site_class: str,
    pack: Any = None,
    z: Any = None,
    zone: Any = None,
) -> SpectralHazard | None:
    """The site's :class:`SpectralHazard` from the settings' ``site.spectral`` block (SDS and
    SD1 entered; else from SMS and SM1 with the pack's design share; else from the MCER
    multi-period spectrum); None without values or when the pack's method is not mapped.
    Alpha 9 C16: ``ubc97`` from the zone coefficient ``z`` and the ``zone`` instead
    (:func:`ubc97_hazard`)."""
    hazard = rule(pack)
    if hazard is not None and hazard.method == UBC97:
        return ubc97_hazard(z, zone, site_class, spectral, pack)
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
    design = getattr(spectral, "designSpectrum", None) or None
    ordinates = getattr(hazard, "ordinates", None)  # Alpha 9 C17: the uniform hazard spectrum
    if (sds is None or sd1 is None) and ordinates is not None and design:
        points = _ordinate_points(design, ordinates)
        lo, hi = ordinates.bandPeriods
        sds, sd1 = _interp(points, lo), _interp(points, hi)
        source = f"the uniform hazard spectrum's S({lo:g}) and S({hi:g})"
        if getattr(spectral, "spectrumFromTown", False):
            source += " of the town"
            reference = ordinates.referenceClass
            if reference is not None and site_class != reference:
                source += (
                    f" for site class {reference} (the site is class {site_class}: enter the "
                    "site's own Sa(T) under Site > Mapped spectral values)"
                )
    if sds is None or sd1 is None or sds <= 0:
        return None
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
    # Alpha 9 C17: the town's uniform hazard spectrum (NBCC 2020 Appendix C type).
    town_spectrum = getattr(location, "spectrum", None) if location is not None else None
    if not any(v is not None for v in town.values()) and not town_spectrum:
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
    if town_spectrum and not merged.get("designSpectrum"):
        merged["designSpectrum"] = [tuple(p) for p in town_spectrum]
        merged["spectrumFromTown"] = True
    return SimpleNamespace(**merged)


def _row(table: dict[str, list[float]], site_class: str, assumed: str | None) -> Any:
    row = table.get(site_class)
    if row is None and assumed is not None:
        row = table.get(assumed)
    return row


def near_source_factors(spectral: Any, ubc: Any) -> tuple[float, float, str]:
    """Alpha 9 C16 (ubc97): (Na, Nv, where they come from): entered Na, Nv; else from the
    seismic source type and the distance by the pack's ``na`` / ``nv`` points; else 1.0."""

    def get(name: str) -> Any:
        return getattr(spectral, name, None) if spectral is not None else None

    na, nv = get("na"), get("nv")
    kind, distance = get("sourceType"), get("sourceDistance")
    source = "entered"
    if (na is None or nv is None) and kind is not None and distance is not None:
        a_pts, v_pts = ubc.na.get(str(kind)), ubc.nv.get(str(kind))
        if a_pts and v_pts:
            if na is None:
                na = _interp(sorted(a_pts), float(distance))
            if nv is None:
                nv = _interp(sorted(v_pts), float(distance))
            source = f"of source type {kind} at {float(distance):g} km"
    if na is None or nv is None:
        return float(na or 1.0), float(nv or 1.0), "not given: taken as 1.0"
    return float(na), float(nv), source


def ubc97_hazard(
    z: Any, zone: Any, site_class: str, spectral: Any = None, pack: Any = None
) -> SpectralHazard | None:
    """Alpha 9 C16: the site's hazard by the ``ubc97`` method: Ca, Cv of the soil profile at
    the zone factor ``z`` (linear between the pack's columns, held beyond), × Na, Nv from the
    pack's ``nearSourceFrom``; a :class:`SpectralHazard` with 2.5 Ca as SDS and Cv as SD1 (no
    S1, no TL), the zone that reads the category table (``zone``, else the pack's zone nearest
    Z) and the least V near the source. None without Z, or for a soil profile with no row (nor
    an ``assumedClass``)."""
    h = rule(pack)
    if h is None or h.ubc97 is None or not z or float(z) <= 0:
        return None
    ubc = h.ubc97
    zf = float(z)
    ca_row = _row(ubc.ca, site_class, ubc.assumedClass)
    cv_row = _row(ubc.cv, site_class, ubc.assumedClass)
    if ca_row is None or cv_row is None:
        return None
    ca = _interp(list(zip(ubc.zValues, ca_row, strict=True)), zf)
    cv = _interp(list(zip(ubc.zValues, cv_row, strict=True)), zf)
    near = ubc.nearSourceFrom is not None and zf >= ubc.nearSourceFrom - 1e-9
    terms: list[tuple[str, Any]] = [("Z", zf), ("soil profile", site_class)]
    floor = None
    where = ""
    if near:
        na, nv, where = near_source_factors(spectral, ubc)
        ca, cv = ca * na, cv * nv
        terms += [("Na", na), ("Nv", nv)]
        if ubc.nearSourceFactor is not None:
            floor = ubc.nearSourceFactor * zf * nv
    terms += [("Ca", ca), ("Cv", cv)]
    if zone is None:
        table = pack.table("zoneCoefficients") if pack is not None else None
        if table is None:
            table = code_context.table("zoneCoefficients")
        zones = table.zones
        zone = min(zones, key=lambda k: abs(zones[k] - zf)) if zones else None
    clause = ubc.clauses.get("coefficients", "")
    source = f"2.5 Ca = {2.5 * ca:.3f} g, Cv = {cv:.3f} g"
    if clause:
        source += f", {clause}"
    if where:
        source += f"; Na, Nv {where}"
    return SpectralHazard(
        2.5 * ca,
        cv,
        None,
        None,
        None,
        source,
        zone=None if zone is None else int(zone),
        terms=terms,
        nearFloor=floor,
        zValue=zf,
        label="seismic coefficients",
    )


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


def _ordinate_points(spectrum: Any, ordinates: Any) -> list[tuple[float, float]]:
    """Alpha 9 C17: the design spectrum S(T) of a uniform hazard spectrum ((T, Sa) points): at
    and below the first of ``ordinates.shortPeriods`` the largest Sa of those periods, the
    ordinates above it, linear between, held at the ends."""
    pts = sorted((float(t), float(a)) for t, a in spectrum)
    short = sorted(float(t) for t in ordinates.shortPeriods)
    plateau = max(_interp(pts, t) for t in short)
    return [(short[0], plateau), *((t, a) for t, a in pts if t > short[0] + 1e-9)]


def spectral_acceleration(period: float, hazard: SpectralHazard, pack: Any = None) -> float:
    """Sa [g] at ``period``: the site's multi-period design spectrum where given (linear
    between its points, held at its ends), else the two-period spectrum. Alpha 9 C17: with
    the pack's ``ordinates`` the short-period plateau of S(T) (:func:`_ordinate_points`)."""
    if hazard.spectrum:
        ordinates = getattr(rule(pack), "ordinates", None)
        if ordinates is not None:
            return _interp(_ordinate_points(hazard.spectrum, ordinates), period)
        return _interp(hazard.spectrum, period)
    return two_period(period, hazard, pack)


def higher_mode_factor(
    period: float, hazard: SpectralHazard, group: str | None, pack: Any = None
) -> float:
    """Alpha 9 C17: Mv of the pack's ``ordinates.higherMode`` table of ``group`` at the
    spectral ratio S(a)/S(b) (``higherModePeriods``) and ``period``, bilinear between the
    points, the end values outside; 1 without a table of the group or a spectrum."""
    ordinates = getattr(rule(pack), "ordinates", None)
    if ordinates is None or not hazard.spectrum:
        return 1.0
    table = ordinates.higherMode.get(group or "default") or ordinates.higherMode.get("default")
    if table is None:
        return 1.0
    a, b = ordinates.higherModePeriods
    long = spectral_acceleration(b, hazard, pack)
    ratio = spectral_acceleration(a, hazard, pack) / long if long > 0 else max(table.ratios)
    rows = [_along(list(table.periods), list(row), period) for row in table.values]
    return _along(list(table.ratios), rows, ratio)


def ordinate_coefficient(
    period: float,
    hazard: SpectralHazard,
    importance: float,
    r: float,
    system: Any = None,
    pack: Any = None,
) -> dict[str, Any]:
    """Alpha 9 C17: V/W of the equivalent static force by the spectrum's ordinates (the
    pack's ``ordinates``, NBCC 2020 4.1.8.11 type): S(T) Mv I/R, at least S(Tmin) Mv I/R of
    the system's group, for systems with Rd at least ``capFromRd`` at most the largest
    share·S(period) of ``capShares`` × I/R. ``{"value", "S", "Mv", "least", "cap",
    "group"}``; ``system`` a ``seismic.systems`` row (None: the 'default' group, no cap)."""
    ordinates = rule(pack).ordinates
    group = getattr(system, "higherModeGroup", None) or "default"
    s_t = spectral_acceleration(period, hazard, pack)
    mv = higher_mode_factor(period, hazard, group, pack)
    ratio = importance / r
    value = s_t * mv * ratio
    out: dict[str, Any] = {
        "S": s_t,
        "Mv": mv,
        "group": group,
        "least": None,
        "cap": None,
        "table": group in ordinates.higherMode or "default" in ordinates.higherMode,
    }
    least_t = ordinates.minimumPeriod.get(group, ordinates.minimumPeriod.get("default"))
    if least_t is not None:
        least = spectral_acceleration(float(least_t), hazard, pack) * mv * ratio
        out["least"] = least
        value = max(value, least)
    rd = getattr(system, "Rd", None)
    applies = ordinates.capFromRd is None or (rd is not None and rd >= ordinates.capFromRd - 1e-9)
    if ordinates.capShares and system is not None and applies:
        cap = max(
            share * spectral_acceleration(t, hazard, pack) for t, share in ordinates.capShares
        )
        cap *= ratio
        out["cap"] = cap
        value = min(value, cap)
    out["value"] = value
    return out


def reduction(
    period: float,
    hazard: SpectralHazard,
    importance: float,
    r: float,
    overstrength: float | None,
    pack: Any = None,
) -> float:
    """Alpha 9 C21: the reduction of the design spectrum Ra(T) by the pack's
    ``shortPeriodReduction`` (TBDY 2018 Eq 4.1): D + (R/I - D) T/TS for T ≤ TS, R/I beyond, D
    the system's ``overstrength``; R/I without the block, without D or for an elastic spectrum
    (R/I at most 1)."""
    ratio = r / importance
    h = rule(pack)
    ramp = getattr(h, "shortPeriodReduction", None) if h is not None else None
    ts = hazard.ts
    if ramp is None or overstrength is None or ratio <= 1.0 or ts <= 0 or period >= ts:
        return ratio
    d = float(overstrength)
    return d + (ratio - d) * max(float(period), 0.0) / ts


def response_coefficient(
    period: float,
    hazard: SpectralHazard,
    importance: float,
    r: float,
    pack: Any = None,
    system: Any = None,
    overstrength: float | None = None,
) -> float:
    """The equivalent lateral force coefficient Cs = SDS/(R/Ie), at most SD1/(T R/Ie) up to TL
    and SD1·TL/(T² R/Ie) beyond, at least the pack's ``csLimits``. Alpha 9 C17: with the
    pack's ``ordinates`` and the site's spectrum, :func:`ordinate_coefficient` instead. Alpha 9
    C21: with the pack's ``shortPeriodReduction``, Sa(T) / Ra(T) of the full spectrum (D the
    ``overstrength``, else the ``system`` row's Ω0), within the same bounds."""
    h = rule(pack)
    if h is not None and h.ordinates is not None and hazard.spectrum:
        return ordinate_coefficient(period, hazard, importance, r, system, pack)["value"]
    ratio = r / importance
    sds, sd1 = float(hazard), hazard.sd1
    ramp = getattr(h, "shortPeriodReduction", None) if h is not None else None
    if overstrength is None and system is not None:
        overstrength = getattr(system, "Omega0", None)
    if ramp is not None and overstrength is not None:  # Alpha 9 C21: SaR = Sae / Ra
        cs = spectral_acceleration(period, hazard, pack) / reduction(
            period, hazard, importance, r, overstrength, pack
        )
    else:
        cs = sds / ratio
        if period > 0:
            if hazard.tl is None or period <= hazard.tl:
                cs = min(cs, sd1 / (period * ratio))
            else:
                cs = min(cs, sd1 * hazard.tl / (period**2 * ratio))
    if hazard.nearFloor is not None:  # Alpha 9 C16 (ubc97): V >= 0.8 Z Nv I W / R
        cs = max(cs, hazard.nearFloor / ratio)
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
    if h.method == UBC97:  # Alpha 9 C16: the zone reads the category table
        return hazard.zone

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
    if h is not None and h.method == UBC97 and h.ubc97 is not None:  # Alpha 9 C16
        steps = sorted((float(a), float(b)) for a, b in h.ubc97.periodUpper)
        z = getattr(hazard, "zValue", None)
        if not steps or z is None:
            return None
        below = [cu for start, cu in steps if start <= z + 1e-9]
        return below[-1] if below else steps[0][1]
    if h is None or not h.periodUpper or not isinstance(hazard, SpectralHazard):
        return None
    pts = sorted((float(a), float(b)) for a, b in h.periodUpper)
    return _interp(pts, hazard.sd1)


def describe(hazard: SpectralHazard) -> str:
    """The site's values in words, for the notes and the report."""
    if hazard.terms:  # Alpha 9 C16 (ubc97): the coefficients the method found
        words = ", ".join(
            f"{n} {v}" if isinstance(v, str) else f"{n} = {float(v):.3g}" for n, v in hazard.terms
        )
        return f"{words} ({hazard.source})" if hazard.source else words
    parts = [f"SDS = {float(hazard):.3f} g", f"SD1 = {hazard.sd1:.3f} g"]
    ordinates = getattr(rule(), "ordinates", None)
    if ordinates is not None and hazard.spectrum:  # Alpha 9 C17: S(T) of the spectrum
        lo, hi = ordinates.bandPeriods
        parts = [f"S({lo:g}) = {float(hazard):.3f} g", f"S({hi:g}) = {hazard.sd1:.3f} g"]
    if hazard.s1 is not None:
        parts.append(f"S1 = {hazard.s1:.3f} g")
    if hazard.tl is not None:
        parts.append(f"TL = {hazard.tl:g} s")
    text = ", ".join(parts)
    if hazard.spectrum:
        text += f"; multi-period design spectrum of {len(hazard.spectrum)} points"
    return f"{text} ({hazard.source})" if hazard.source else text

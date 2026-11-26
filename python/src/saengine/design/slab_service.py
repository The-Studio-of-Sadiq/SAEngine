"""Long-term cracked deflection and crack widths of slabs analysed as shells (#302).

Per design strip bay (:mod:`saengine.design.slab`: column and middle strips, one bay each),
from the analysis's unfactored dead (D + SD) and live (L + Lr) cases and the slab's own bars
(per metre width, the strip's direction's layers):

- **Deflection.** The analysis's elastic deflection of the bay, relative to its supports (the
  mean deflection of the slab's nodes on the columns and walls of each support line; without
  any, the strip's own nodes there), scaled from the analysis's plate stiffness E I to the
  cracked stiffness Ec Ie of the bars provided, Ie by the code pack's method:

  - ``effectiveInertia`` (``concrete.deflection``): Ie of :func:`saengine.design.deflection.
    effective_inertia` (the pack's cubic or Bischoff form) at mid-span (sagging, bottom bars)
    and at the supported ends (hogging, top bars), averaged
    (:func:`saengine.design.deflection.averaged_inertia`; a cantilever: its support);
    long-term part λΔ = ξ / (1 + 50 ρ') times the immediate deflection under D + ψ L (ξ of the
    months the load is sustained, ρ' at mid-span); immediate live-load deflection and the part
    after the nonstructural elements are attached against the pack's limits;
  - ``interpolation`` (``concrete.slabService``): 1/Ie = ζ/Icr + (1 - ζ)/Ig, ζ = 1 - β
    (Mcr/M)², Mcr = fctm Ig / yt; the final deflection under the quasi-permanent load D + ψ L
    with Ec,eff = Ec / (1 + φ) (β sustained), against l / limitTotal, and that less the
    immediate dead-load deflection against l / limitAfter (shrinkage curvature not included);
  - ``spanDepthModification`` (``concreteMethods.deflection``, Annex C type): Ieff of
    :func:`saengine.design.span_depth_factors.effective_inertia` under D + L, creep θ of the
    permanent part and the shrinkage deflection, against the pack's limitTotal and limitAfter;
  - ``longTermStiffness`` (``concreteMethods.deflection``): B = Bs / θ of
    :func:`saengine.design.tension_stiffening.stiffness` under Mq = D + ψq L, against l0 /
    divisor.

- **Crack widths** at mid-span (bottom bars) and at the supported ends (top bars) of each bay,
  and per shell from its mean moments (Wood-Armer, each layer), by the pack's
  ``concreteMethods.cracking`` method: ``directWidth`` (:func:`saengine.design.crack_control.
  crack_width`, quasi-permanent D + ψ L), ``strainSpacing`` (:func:`saengine.design.
  span_depth_factors.crack_width`, D + L) or ``effectiveTensionRatio`` (:func:`saengine.design.
  tension_stiffening.crack_width`, D + ψq L); a pack without one but with the bar spacing rule
  (``detailing.crackControl``) checks the spacing of the bars at the service steel stress
  instead (D + L). A pack with neither: not provided by this code.

What the design run collects (:class:`SlabServiceData`) is kept in the design report, so the
inputs (ψ, the months, φ, the partitions) can be changed without a new design run
(:func:`evaluate`). Units: mm, N, MPa, N·mm (moments per metre width: N·mm/m).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any

import numpy as np

from saengine.design import deflection as defl
from saengine.design.rc import Bar, DesignError, RcSection, bar_area
from saengine.library.objects import RectangleProfile

NOT_PROVIDED = "not provided by this code"
#: The method names, as the report and the panels show them.
METHOD_NAMES = {
    "effectiveInertia": "effective moment of inertia Ie and λΔ = ξ/(1 + 50ρ')",
    "interpolation": "ζ interpolation between the uncracked and cracked states, Ec,eff = Ec/(1 + φ)",
    "spanDepthModification": "Ieff with creep θ and shrinkage",
    "longTermStiffness": "long-term stiffness B = Bs/θ under Mq",
    "directWidth": "wk = sr,max (εsm - εcm)",
    "strainSpacing": "Wcr = 3 acr εm / (1 + 2 (acr - cmin)/(h - x))",
    "effectiveTensionRatio": "wmax = αcr ψ σs/Es (c cs + b deq/ρte)",
    "barSpacing": "bar spacing at the service steel stress",
}


# ─────────────────────────────────────── inputs and data ───────────────────────────────────────


@dataclass(frozen=True)
class Inputs:
    """What the engineer sets: the sustained share ψ of the live load (the quasi-permanent
    load D + ψ L), the months it is sustained (ξ), whether the partitions are likely to be
    damaged, φ (None: the pack's) and the exposure (None: the project's or the pack's)."""

    sustained: float = 0.25
    months: float = 60.0
    sensitive: bool = True
    creep: float | None = None
    exposure: str | None = None


@dataclass(frozen=True)
class LayerData:
    """One layer of bars per metre: diameter, spacing and effective depth [mm]."""

    dia: float
    spacing: float
    d: float

    @property
    def area(self) -> float:
        return bar_area(self.dia) * 1000.0 / self.spacing


@dataclass(frozen=True)
class SpanData:
    """One bay of a design strip: its moments per metre (dead, live) at mid-span (sagging
    positive) and at its supported ends (hogging positive), and the analysis's deflection
    (dead, live) [mm, downward positive] relative to its supports."""

    strip: str
    direction: str  # "X" or "Y"
    kind: str  # "column", "middle" or "strip"
    span: float  # mm
    cantilever: bool
    continuous: int  # ends continuous over a support (0, 1, 2)
    mid: tuple[float, float]
    ends: tuple[tuple[float, float], ...]
    delta: tuple[float, float]


@dataclass(frozen=True)
class ShellData:
    """One analysis shell: its deflection (dead, live) [mm] relative to the slab's supports,
    its mean moments per case (mx, my, mxy of dead, then of live) [N·mm/m] and the bays
    (indices of :attr:`SlabServiceData.spans`) its centre lies in."""

    id: int
    delta: tuple[float, float]
    moments: tuple[float, ...]
    spans: tuple[int, ...]


@dataclass(frozen=True)
class SlabServiceData:
    """What the design run collects of one slab (see the module notes)."""

    slab: str
    h: float
    fc: float
    fy: float
    es: float
    ec: float
    ei: float  # the analysis's plate E I per metre width [N·mm²]
    roof: bool
    layers: dict[str, LayerData | None]
    spans: list[SpanData] = field(default_factory=list)
    shells: list[ShellData] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> SlabServiceData:
        layers = {
            k: (LayerData(**v) if v is not None else None)
            for k, v in (raw.get("layers") or {}).items()
        }
        spans = [
            SpanData(
                **{
                    **s,
                    "mid": tuple(s["mid"]),
                    "ends": tuple(tuple(e) for e in s["ends"]),
                    "delta": tuple(s["delta"]),
                }
            )
            for s in raw.get("spans") or []
        ]
        shells = [
            ShellData(int(s["id"]), tuple(s["delta"]), tuple(s["moments"]), tuple(s["spans"]))
            for s in raw.get("shells") or []
        ]
        scalars = {k: raw[k] for k in ("slab", "h", "fc", "fy", "es", "ec", "ei", "roof")}
        return cls(**scalars, layers=layers, spans=spans, shells=shells)


# ─────────────────────────────────────── the pack's methods ───────────────────────────────────


def _concrete_group(name: str) -> Any | None:
    from saengine.codes import context as code_context

    try:
        return getattr(code_context.table("concrete"), name, None)
    except (KeyError, AttributeError, LookupError):
        return None


def slab_rules() -> Any | None:
    """The pack's ``concrete.slabService`` (ζ interpolation), or None."""
    return _concrete_group("slabService")


def deflection_method() -> str | None:
    """The pack's method of the slabs' cracked deflection (see the module notes), or None."""
    from saengine.design import span_depth_factors, tension_stiffening

    if slab_rules() is not None:
        return "interpolation"
    if tension_stiffening.deflection_rules() is not None:
        return "longTermStiffness"
    if span_depth_factors.rules() is not None:
        return "spanDepthModification"
    if _concrete_group("deflection") is not None:
        return "effectiveInertia"
    return None


def crack_method() -> str | None:
    """The pack's method of the slabs' crack widths (see the module notes), or None."""
    from saengine.design import crack_control, span_depth_factors, tension_stiffening
    from saengine.design.rc_detailing import crack_spacing_limit

    if crack_control.covered("cracking"):
        return "directWidth"
    if span_depth_factors.crack_rules() is not None:
        return "strainSpacing"
    if tension_stiffening.crack_rules() is not None:
        return "effectiveTensionRatio"
    if crack_spacing_limit(250.0, 25.0) is not None:
        return "barSpacing"
    return None


def _exposure_limit(widths: Mapping[str, float], wanted: str | None) -> tuple[str, float]:
    """(exposure, limit [mm]) of the crack width table ``widths``: ``wanted``, else the
    project's exposure in force, else the pack's default, else the smallest limit."""
    from saengine.design.member_limits import exposure
    from saengine.design.tabulated_shear import _table

    keys = [wanted] if wanted else []
    found = exposure()
    if found:
        keys.append(found[0])
    table = _table()
    default = getattr(table, "defaultExposure", None) if table is not None else None
    if default:
        keys.append(default)
    for key in keys:
        if key in widths:
            return key, float(widths[key])
    key = min(widths, key=lambda k: widths[k])
    return key, float(widths[key])


# ─────────────────────────────────────── sections ───────────────────────────────────────


def strip_section(data: SlabServiceData, direction: str, width: float = 1000.0) -> RcSection:
    """A ``width`` wide section of the slab with the ``direction``'s bottom and top layers as
    bars spread evenly across it, their area per metre kept (y up from mid-depth)."""
    return _section(*_key(data, direction), width)


def _key(data: SlabServiceData, direction: str) -> tuple[Any, ...]:
    return (
        data.h,
        data.fc,
        data.fy,
        data.es,
        data.layers.get(f"bottom{direction}"),
        data.layers.get(f"top{direction}"),
    )


@lru_cache(maxsize=4096)
def _section(
    h: float,
    fc: float,
    fy: float,
    es: float,
    bottom: LayerData | None,
    top: LayerData | None,
    width: float,
) -> RcSection:
    bars: list[Bar] = []
    for face, layer in (("bottom", bottom), ("top", top)):
        if layer is None:
            continue
        count = max(1, round(width / layer.spacing))
        area = layer.area * width / 1000.0 / count
        y = (h / 2 - layer.d) if face == "bottom" else (layer.d - h / 2)
        step = width / count
        for k in range(count):
            bars.append(Bar(-width / 2 + step * (k + 0.5), y, area, layer.dia))
    return RcSection(RectangleProfile(xDim=width, yDim=h), tuple(bars), fc, fy, es)


@lru_cache(maxsize=4096)
def _stiffness(key: tuple[Any, ...], width: float, ec: float, hogging: bool) -> Any:
    try:
        return defl.section_stiffness(_section(*key, width), ec, hogging=hogging)
    except (ValueError, DesignError) as error:
        return error


def stiffness(
    data: SlabServiceData, direction: str, ec: float, hogging: bool, width: float = 1000.0
) -> defl.SectionStiffness:
    """:func:`saengine.design.deflection.section_stiffness` of :func:`strip_section`, kept for
    the next call with the same bars (the slab's shells and bays share a few sections)."""
    found = _stiffness(_key(data, direction), width, ec, hogging)
    if isinstance(found, Exception):
        raise found
    return found


def crack_section(
    data: SlabServiceData, layer: LayerData, direction: str
) -> tuple[RcSection, float]:
    """(section, width [mm]) for the crack widths: a whole number of the tension bars'
    spacings wide (about a metre), so the bars lie at their own spacing, half of it from each
    edge (the worst point of the face midway between two bars); moments per metre × width/1000."""
    width = max(1, round(1000.0 / layer.spacing)) * layer.spacing
    return strip_section(data, direction, width), width


def _tension_layer(data: SlabServiceData, direction: str, hogging: bool) -> LayerData | None:
    return data.layers.get(f"{'top' if hogging else 'bottom'}{direction}")


# ─────────────────────────────────────── deflection ───────────────────────────────────────


@dataclass(frozen=True)
class SpanResult:
    """The deflections of one bay [mm] and its checks: (name, value, limit, note)."""

    method: str
    immediate: float  # under D + L, short-term
    long_term: float  # the time-dependent part
    total: float  # the final deflection the limits speak of
    after: float  # after the partitions (construction)
    scale: float  # total = scale × (δD + weight δL) of the analysis
    weight: float
    checks: tuple[tuple[str, float, float, str], ...]
    note: str


def _scale(elastic: float, ei: float, stiffness: float) -> float:
    return elastic * ei / stiffness if stiffness > 0 else 0.0


def _effective_inertia(span: SpanData, data: SlabServiceData, inputs: Inputs) -> SpanResult:
    limits = defl.DeflectionLimits.from_pack()
    method = defl.inertia_method()
    ec = data.ec
    ends: list[tuple[defl.SectionStiffness, tuple[float, float]]] = []
    if span.cantilever:
        mid, mid_m = stiffness(data, span.direction, ec, True), span.ends[0]
    else:
        mid, mid_m = stiffness(data, span.direction, ec, False), span.mid
        for moment in span.ends:
            try:
                ends.append((stiffness(data, span.direction, ec, True), moment))
            except ValueError:
                continue  # no top bars: the mid-span section alone

    def ie(share: float) -> float:
        def one(s: defl.SectionStiffness, m: tuple[float, float]) -> float:
            mcr = defl.cracking_moment(data.fc, s.ig, s.yt)
            return defl.effective_inertia(max(m[0] + share * m[1], 0.0), mcr, s.ig, s.icr, method)

        return defl.averaged_inertia(one(mid, mid_m), [one(s, m) for s, m in ends])

    psi = inputs.sustained
    d_d, d_l = max(span.delta[0], 0.0), max(span.delta[1], 0.0)
    i_dead = _scale(d_d, data.ei, ec * ie(0.0))
    i_total = _scale(d_d + d_l, data.ei, ec * ie(1.0))
    i_sus = _scale(d_d + psi * d_l, data.ei, ec * ie(psi))
    i_live = max(i_total - i_dead, 0.0)
    xi = defl.xi_factor(inputs.months, limits.xi)
    lam = defl.long_term_multiplier(mid.rho_prime, xi)
    long_term = lam * i_sus
    total = i_total + long_term
    after = long_term + i_live
    live_div = limits.live_roof if data.roof else limits.live_floor
    attached = limits.attached_sensitive if inputs.sensitive else limits.attached_insensitive
    elastic = d_d + d_l
    clause = defl.row_clause("limits")
    checks = (
        (
            "Deflection: immediate, live load (FE slab, cracked)",
            i_live,
            span.span / live_div,
            f"l/{live_div:g} ({'flat roof' if data.roof else 'floor'})"
            + (f" ({clause})" if clause else ""),
        ),
        (
            "Deflection: after attachment of nonstructural elements (FE slab, cracked)",
            after,
            span.span / attached,
            f"λΔ × immediate sustained + immediate live, l/{attached:g}"
            + (f" ({clause})" if clause else ""),
        ),
    )
    note = (
        f"Ie by '{method}' averaged mid-span and supports: {ie(0.0):.4g} (D), {ie(psi):.4g} "
        f"(D + {psi:g} L), {ie(1.0):.4g} (D + L) mm⁴/m, Ig {mid.ig:.4g}; λΔ = {xi:g}/(1 + 50 × "
        f"{mid.rho_prime:.4f}) = {lam:.2f}"
    )
    return SpanResult(
        "effectiveInertia",
        i_total,
        long_term,
        total,
        after,
        total / elastic if elastic > 0 else 0.0,
        1.0,
        checks,
        note,
    )


def zeta_inertia(m: float, mcr: float, ig: float, icr: float, beta: float) -> float:
    """1/Ie = ζ/Icr + (1 - ζ)/Ig, ζ = 1 - β (Mcr/M)², ζ = 0 up to Mcr [mm⁴]."""
    m = abs(m)
    if m <= mcr or icr <= 0:
        return ig
    zeta = 1.0 - beta * (mcr / m) ** 2
    return 1.0 / (zeta / icr + (1.0 - zeta) / ig)


def _interpolation(span: SpanData, data: SlabServiceData, inputs: Inputs) -> SpanResult:
    from saengine.design import design_strength

    r = slab_rules()
    phi = inputs.creep if inputs.creep is not None else float(r.creepCoefficient)
    beta_short, beta_long = (float(b) for b in r.beta)
    fctm = design_strength.properties(data.fc).fctm
    ec, ec_eff = data.ec, data.ec / (1.0 + phi)

    def ie(e: float, share: float, beta: float) -> float:
        def one(hogging: bool, m: tuple[float, float]) -> float:
            s = stiffness(data, span.direction, e, hogging)
            return zeta_inertia(m[0] + share * m[1], fctm * s.ig / s.yt, s.ig, s.icr, beta)

        if span.cantilever:
            return one(True, span.ends[0])
        ends = []
        for m in span.ends:
            try:
                ends.append(one(True, m))
            except ValueError:
                continue
        return defl.averaged_inertia(one(False, span.mid), ends)

    psi = inputs.sustained
    d_d, d_l = max(span.delta[0], 0.0), max(span.delta[1], 0.0)
    i_dead = _scale(d_d, data.ei, ec * ie(ec, 0.0, beta_short))
    i_total = _scale(d_d + d_l, data.ei, ec * ie(ec, 1.0, beta_short))
    i_qp = _scale(d_d + psi * d_l, data.ei, ec * ie(ec, psi, beta_short))
    final = _scale(d_d + psi * d_l, data.ei, ec_eff * ie(ec_eff, psi, beta_long))
    after = max(final - i_dead, 0.0)
    elastic = d_d + psi * d_l
    checks = (
        (
            "Deflection: final, quasi-permanent (FE slab, cracked)",
            final,
            span.span / r.limitTotal,
            f"D + {psi:g} L with Ec,eff = Ec/(1 + {phi:g}), l/{r.limitTotal:g}",
        ),
        (
            "Deflection: after construction (FE slab, cracked)",
            after,
            span.span / r.limitAfter,
            f"final less the immediate dead-load deflection {i_dead:.1f} mm, l/{r.limitAfter:g}",
        ),
    )
    note = (
        f"ζ interpolation, β {beta_short:g}/{beta_long:g}, Mcr = fctm Ig/yt (fctm {fctm:.2f} MPa), "
        f"φ = {phi:g}; shrinkage curvature not included"
    )
    return SpanResult(
        "interpolation",
        i_total,
        max(final - i_qp, 0.0),
        final,
        after,
        final / elastic if elastic > 0 else 0.0,
        psi,
        checks,
        note,
    )


def _span_depth_modification(span: SpanData, data: SlabServiceData, inputs: Inputs) -> SpanResult:
    from saengine.design import span_depth_factors as sdf

    r = sdf.rules()
    hogging = span.cantilever
    s = stiffness(data, span.direction, data.ec, hogging)
    m = span.ends[0] if span.cantilever else span.mid
    m_total = max(m[0], 0.0) + max(m[1], 0.0)
    mr = r.ruptureCoefficient * math.sqrt(data.fc) * s.ig / s.yt
    ieff = sdf.effective_inertia(s.icr, s.ig, mr, m_total, s.d - s.c / 3, s.d, s.c)
    d_d, d_l = max(span.delta[0], 0.0), max(span.delta[1], 0.0)
    short_d = _scale(d_d, data.ei, data.ec * ieff)
    short_l = _scale(d_l, data.ei, data.ec * ieff)
    theta = inputs.creep if inputs.creep is not None else sdf.creep_coefficient()
    creep = theta * (short_d + inputs.sustained * short_l)
    tension = _tension_layer(data, span.direction, hogging)
    compression = _tension_layer(data, span.direction, not hogging)
    pt = 100 * (tension.area if tension else 0.0) / (1000 * s.d)
    pc = 100 * (compression.area if compression else 0.0) / (1000 * s.d)
    kind = sdf.support_kind(span.continuous, span.cantilever)
    if kind == "continuous" and span.continuous == 1:
        kind = "continuousOne"
    shrink = sdf.shrinkage_deflection(span.span, data.h, pt, pc, kind)
    total = short_d + short_l + creep + shrink
    after = creep + shrink + short_l
    elastic = d_d + d_l
    checks = (
        (
            "Deflection: final, calculated (FE slab, cracked)",
            total,
            span.span / r.limitTotal,
            f"l/{r.limitTotal:g}",
        ),
        (
            "Deflection: after the partitions (FE slab, cracked)",
            after,
            min(span.span / r.limitAfter, r.limitAfterMax),
            f"creep + shrinkage + live, l/{r.limitAfter:g} and {r.limitAfterMax:g} mm",
        ),
    )
    note = (
        f"Ieff = {ieff:.4g} mm⁴/m (Ir {s.icr:.4g}, Igr {s.ig:.4g}); creep θ = {theta:.2f}: "
        f"{creep:.1f} mm, shrinkage {shrink:.1f} mm"
    )
    return SpanResult(
        "spanDepthModification",
        short_d + short_l,
        creep + shrink,
        total,
        after,
        total / elastic if elastic > 0 else 0.0,
        1.0,
        checks,
        note,
    )


def _long_term_stiffness(span: SpanData, data: SlabServiceData, inputs: Inputs) -> SpanResult:
    from saengine.design import tension_stiffening as ts

    r = ts.deflection_rules()
    psi_q = float(r.liveShare)
    hogging = span.cantilever
    m = span.ends[0] if span.cantilever else span.mid
    mq = max(m[0], 0.0) + psi_q * max(m[1], 0.0)
    if mq <= 0:
        raise ValueError("no sagging moment under Mq")
    b_long, how = ts.stiffness(strip_section(data, span.direction), mq, hogging, data.ec)
    d_d, d_l = max(span.delta[0], 0.0), max(span.delta[1], 0.0)
    elastic = d_d + psi_q * d_l
    f = _scale(elastic, data.ei, b_long)
    l0 = r.cantileverFactor * span.span if span.cantilever else span.span
    divisor = ts.limit_divisor(l0)
    checks = (
        (
            "Deflection: long-term, calculated (FE slab, cracked)",
            f,
            l0 / divisor,
            f"Mq = D + {psi_q:g} L, l0/{divisor:g}, l0 = {l0:.0f} mm",
        ),
    )
    return SpanResult(
        "longTermStiffness",
        _scale(d_d + d_l, data.ei, b_long),
        0.0,
        f,
        f,
        f / elastic if elastic > 0 else 0.0,
        psi_q,
        checks,
        how,
    )


_DEFLECTION = {
    "effectiveInertia": _effective_inertia,
    "interpolation": _interpolation,
    "spanDepthModification": _span_depth_modification,
    "longTermStiffness": _long_term_stiffness,
}


def span_deflection(
    span: SpanData, data: SlabServiceData, inputs: Inputs, method: str | None = None
) -> SpanResult:
    """The deflections of one bay by the pack's method (``method``: :func:`deflection_method`)."""
    method = method or deflection_method()
    if method is None:
        raise ValueError(NOT_PROVIDED)
    if not 0 <= inputs.sustained <= 1:
        raise ValueError("the sustained share of the live load must be between 0 and 1")
    return _DEFLECTION[method](span, data, inputs)


# ─────────────────────────────────────── crack widths ───────────────────────────────────────


@dataclass(frozen=True)
class CrackResult:
    """A crack width [mm] (``barSpacing``: the bars' spacing [mm]) against its limit."""

    method: str
    value: float
    limit: float
    exposure: str
    note: str
    stress: float = 0.0  # MPa, the service steel stress where the method works it


def crack_load_share(method: str, inputs: Inputs) -> float:
    """The share of the live load in the crack width's service moment."""
    from saengine.design import tension_stiffening as ts

    if method == "directWidth":
        return inputs.sustained
    if method == "effectiveTensionRatio":
        return float(ts.crack_rules().liveShare)
    return 1.0


def crack_width(
    data: SlabServiceData,
    direction: str,
    hogging: bool,
    moment: float,
    inputs: Inputs,
    method: str | None = None,
) -> CrackResult | None:
    """The crack width of the ``direction``'s layer on the tension face under ``moment``
    [N·mm/m, positive] by the pack's method; None without bars there or a moment."""
    from saengine.design import crack_control, span_depth_factors, tension_stiffening
    from saengine.design.rc_detailing import crack_spacing_limit

    method = method or crack_method()
    layer = _tension_layer(data, direction, hogging)
    if method is None or layer is None or moment <= 0:
        return None
    section, width = crack_section(data, layer, direction)
    scaled = moment * width / 1000.0  # on the section's width
    cover = data.h - layer.d - layer.dia / 2
    if method == "directWidth":
        c = crack_control._table().cracking
        cw = crack_control.crack_width(
            1000.0, data.h, layer.d, layer.area, layer.dia, cover, moment, data.fc, data.es,
            layer.spacing,
        )  # fmt: skip
        key, limit = _exposure_limit(c.wmax, inputs.exposure)
        note = f"σs = {cw.sigma_s:.0f} MPa, sr,max = {cw.sr_max:.0f} mm, ρp,eff = {cw.rho_eff:.4f}"
        return CrackResult(method, cw.wk, limit, key, note)
    if method == "strainSpacing":
        c = span_depth_factors.crack_rules()
        s = stiffness(data, direction, data.ec, hogging, width)
        w, how = span_depth_factors.crack_width(section, s, scaled, hogging, data.ec)
        key, limit = _exposure_limit(c.width, inputs.exposure)
        return CrackResult(method, w, limit, key, how)
    if method == "effectiveTensionRatio":
        c = tension_stiffening.crack_rules()
        w, how = tension_stiffening.crack_width(section, scaled, hogging)
        key, limit = _exposure_limit(c.width, inputs.exposure)
        return CrackResult(method, w, limit, key, how)
    # barSpacing: the steel stress of the cracked section under the service moment.
    s = stiffness(data, direction, data.ec, hogging, width)
    n = data.es / data.ec
    fs = n * scaled * (s.d - s.c) / s.icr if s.icr > 0 else 0.0
    limit = crack_spacing_limit(fs, cover) if fs > 0 else None
    if limit is None:
        return None
    return CrackResult(
        method,
        layer.spacing,
        max(limit, 0.0),
        "",
        f"fs = {fs:.0f} MPa (cracked section), cc = {cover:.0f} mm; crack widths are not "
        "calculated by this code",
        fs,
    )


# ─────────────────────────────────────── evaluation ───────────────────────────────────────


@dataclass
class Evaluated:
    """The results of one slab: the rows of the design checks (governing per check), the
    table rows per bay and station, the per-shell contours and notes."""

    deflection_method: str | None
    crack_method: str | None
    checks: list[dict[str, Any]] = field(default_factory=list)
    spans: list[dict[str, Any]] = field(default_factory=list)
    cracks: list[dict[str, Any]] = field(default_factory=list)
    deflection: dict[str, float] = field(default_factory=dict)
    crack: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "deflectionMethod": self.deflection_method,
            "crackMethod": self.crack_method,
            "deflectionMethodName": METHOD_NAMES.get(self.deflection_method or "", NOT_PROVIDED),
            "crackMethodName": METHOD_NAMES.get(self.crack_method or "", NOT_PROVIDED),
            # The crack contour: a width [mm], or (bar spacing) the service steel stress [MPa].
            "crackQuantity": "stress" if self.crack_method == "barSpacing" else "width",
            "spans": self.spans,
            "cracks": self.cracks,
            "deflection": self.deflection,
            "crack": self.crack,
            "notes": self.notes,
        }


def _governing(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The row of each check name with the largest utilisation."""
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        kept = best.get(row["name"])
        if kept is None or row["utilisation"] > kept["utilisation"]:
            best[row["name"]] = row
    return list(best.values())


def evaluate(data: SlabServiceData, inputs: Inputs, deflection: bool = True) -> Evaluated:
    """The deflections and crack widths of a slab (see the module notes) under ``inputs``;
    ``deflection`` False: the crack widths only."""
    from saengine.design.check import _check
    from saengine.design.slab import wood_armer

    d_method = deflection_method() if deflection else None
    c_method = crack_method()
    out = Evaluated(d_method, c_method)
    if deflection and d_method is None:
        out.notes.append(f"{data.slab}: cracked deflection {NOT_PROVIDED}")
    if c_method is None:
        out.notes.append(f"{data.slab}: crack widths {NOT_PROVIDED}")
    rows: list[dict[str, Any]] = []
    scales: list[tuple[float, float] | None] = []
    for span in data.spans:
        where = f"{data.slab} {span.strip}, l = {span.span / 1e3:.2f} m"
        result: SpanResult | None = None
        if d_method is not None:
            try:
                result = span_deflection(span, data, inputs, d_method)
            except (DesignError, ValueError, ZeroDivisionError, AttributeError) as error:
                out.notes.append(f"{where}: deflection not computed: {error}")
        scales.append((result.scale, result.weight) if result is not None else None)
        if result is not None:
            out.spans.append(
                {
                    "strip": span.strip,
                    "direction": span.direction,
                    "kind": span.kind,
                    "span": round(span.span, 1),
                    "cantilever": span.cantilever,
                    "elasticD": round(span.delta[0], 3),
                    "elasticL": round(span.delta[1], 3),
                    "immediate": round(result.immediate, 3),
                    "longTerm": round(result.long_term, 3),
                    "total": round(result.total, 3),
                    "after": round(result.after, 3),
                    "checks": [
                        {
                            "name": n,
                            "value": round(v, 3),
                            "limit": round(lim, 3),
                            "ok": v <= lim,
                            "note": how,
                        }
                        for n, v, lim, how in result.checks
                    ],
                    "note": result.note,
                }
            )
            for name, value, limit, how in result.checks:
                rows.append(
                    _check(name, value, limit, "mm", "service", f"{how}; {result.note}; {where}")
                )
        # Crack widths at mid-span (bottom bars) and at the supported ends (top bars).
        if c_method is None:
            continue
        share = crack_load_share(c_method, inputs)
        stations: list[tuple[str, bool, tuple[float, float]]] = []
        if not span.cantilever:
            stations.append(("mid-span", False, span.mid))
        # Two ends: the one at the strip's start (lower x or y) first (collect's order).
        axis = span.direction.lower()
        sides = (f"support at lower {axis}", f"support at higher {axis}")
        stations += [
            (sides[i] if len(span.ends) == 2 else "support", True, m)
            for i, m in enumerate(span.ends)
        ]
        for at, hogging, m in stations:
            moment = m[0] + share * m[1]
            try:
                found = crack_width(data, span.direction, hogging, moment, inputs, c_method)
            except (DesignError, ValueError, ZeroDivisionError, AttributeError) as error:
                out.notes.append(f"{where} ({at}): crack width not computed: {error}")
                continue
            if found is None:
                continue
            out.cracks.append(
                {
                    "strip": span.strip,
                    "at": at,
                    "face": "top" if hogging else "bottom",
                    "moment": round(moment / 1e6, 3),  # kN·m/m
                    "value": round(found.value, 3),
                    "limit": round(found.limit, 3),
                    "ok": found.value <= found.limit,
                    "exposure": found.exposure,
                    "note": found.note,
                }
            )
            name = (
                "Crack control: bar spacing at service (FE slab)"
                if c_method == "barSpacing"
                else "Crack width (FE slab)"
            )
            exposure = f"; exposure '{found.exposure}'" if found.exposure else ""
            rows.append(
                _check(
                    name,
                    found.value,
                    found.limit,
                    "mm",
                    "service",
                    f"{found.note}{exposure}; {at}, {'top' if hogging else 'bottom'} bars; {where}",
                )
            )
    # The contours: per shell the deflection scaled as its bay's, and its crack width.
    for shell in data.shells:
        if d_method is not None:
            found_scales = [scales[k] for k in shell.spans if k < len(scales) and scales[k]]
            if found_scales:
                value = max(
                    s * (max(shell.delta[0], 0.0) + w * max(shell.delta[1], 0.0))
                    for s, w in found_scales
                )
                out.deflection[str(shell.id)] = round(value, 3)
        if c_method is not None and len(shell.moments) >= 6:
            share = crack_load_share(c_method, inputs)
            mx, my, mxy = (shell.moments[k] + share * shell.moments[k + 3] for k in range(3))
            worst = 0.0
            design = wood_armer(mx, my, mxy)
            for k, name in enumerate(("bottomX", "bottomY", "topX", "topY")):
                moment = design[k]
                try:
                    found = crack_width(
                        data, name[-1], name.startswith("top"), moment, inputs, c_method
                    )
                except (DesignError, ValueError, ZeroDivisionError, AttributeError):
                    continue
                if found is None:
                    continue
                value = found.stress if c_method == "barSpacing" else found.value
                worst = max(worst, value)
            out.crack[str(shell.id)] = round(worst, 3)
    out.checks = _governing(rows)
    return out


# ─────────────────────────────────────── collection ───────────────────────────────────────


def _support_nodes(
    nodes: np.ndarray, columns: Sequence[Any], supports: Sequence[Any], reach: float
) -> np.ndarray:
    """Which plan points [mm] lie on a column or a wall (within ``reach`` of it)."""
    found = np.zeros(len(nodes), dtype=bool)
    for c in columns:
        radius = max(c.c1, c.c2) / 2 + reach
        found |= np.hypot(nodes[:, 0] - c.centre[0], nodes[:, 1] - c.centre[1]) <= radius
    for s in supports:
        if getattr(s, "kind", "") != "wall":
            continue
        a, b = np.asarray(s.start, dtype=float), np.asarray(s.end, dtype=float)
        ab = b - a
        length2 = float(ab @ ab) or 1.0
        t = np.clip(((nodes - a) @ ab) / length2, 0.0, 1.0)
        nearest = a + t[:, None] * ab
        found |= np.hypot(*(nodes - nearest).T) <= s.width / 2 + reach
    return found


def collect(
    slab_id: str,
    context: Any,
    shells: Sequence[Any],
    node_ids: Mapping[int, Sequence[int]],
    coords: Mapping[int, np.ndarray],
    displacement: Mapping[str, Mapping[int, np.ndarray]],
    h: float,
    fc: float,
    fy: float,
    es: float,
    ec: float,
    ei: float,
    layers: Mapping[str, Any],
    roof: bool,
) -> SlabServiceData:
    """What :func:`evaluate` needs of one slab, from its design (``context``: the
    :class:`saengine.design.slab.SlabContext` its checks filled, with the strips), its shells
    with their forces per case (:class:`saengine.design.slab.ShellPoint`, ``forces`` [dead,
    live]: N·m/m), their nodes, the node coordinates [m] and the nodes' displacements per case
    ("D", "L": [m], dead D + SD, live L + Lr)."""
    from saengine.design import slab as slab_design

    frame = slab_design.PlanFrame(context.axes)
    positions = [p for shell in shells for p in shell.points]
    count = len(positions)
    if not count:
        raise ValueError("the slab's shells have no results")
    if all(shell.areas is not None for shell in shells):
        areas = np.array([a for shell in shells for a in shell.areas or []], dtype=float)
    else:
        areas = np.ones(count)
    forces = np.stack(
        [np.concatenate([shell.forces[c] for shell in shells]) for c in range(2)], axis=1
    )  # (points, case, mx my mxy qx qy) [N·m/m]
    local = np.array([frame.local(p[:2] * 1e3) for p in positions])
    outline = [frame.local(p) for p in context.boundary] if len(context.boundary) >= 3 else []
    area = slab_design._polygon_area(outline) if outline else 0.0
    mesh = slab_design.mesh_size(area, count)
    groups = np.repeat(np.arange(len(shells)), [len(shell.points) for shell in shells])
    plan = np.hstack([local, np.array([p[:2] for p in positions]) * 1e3])
    centres, means, weights = slab_design.element_means(
        groups, plan, forces, areas, np.ones(count, bool)
    )
    inside = np.array(
        [slab_design._near_column(c[2:] / 1e3, context.columns, 0.0) for c in centres]
    )

    # The nodes' deflections [mm, downward positive], dead and live.
    ids = sorted({n for shell in shells for n in node_ids.get(shell.id, ())})
    node_plan = np.array([np.asarray(coords[n], dtype=float)[:2] * 1e3 for n in ids])
    node_local = np.array([frame.local(p) for p in node_plan])

    def down(case: str) -> np.ndarray:
        moved = displacement.get(case) or {}
        return np.array([-float(np.asarray(moved.get(n, np.zeros(6)))[2]) * 1e3 for n in ids])

    u = np.stack([down("D"), down("L")], axis=1)  # (nodes, 2)
    on_support = _support_nodes(node_plan, context.columns, context.supports, mesh / 2)

    def reference(along: int, at: float, lo: float, hi: float) -> np.ndarray | None:
        """The supports' mean deflection on the line at ``at`` along [mm]: their nodes there,
        else the strip's own nodes there; None without nodes."""
        near = np.abs(node_local[:, along] - at) <= mesh / 2 + 1.0
        chosen = near & on_support
        if not chosen.any():
            across = node_local[:, 1 - along]
            chosen = near & (across >= lo - 1.0) & (across <= hi + 1.0)
        return u[chosen].mean(axis=0) if chosen.any() else None

    spans: list[SpanData] = []
    regions: list[tuple[int, float, float, float, float]] = []  # along, a, b, lo, hi
    for strip in context.strips:
        along = 0 if strip.direction == "X" else 1
        supported = (strip.before > 0, strip.after > 0)
        if not any(supported):
            continue  # a direction without supports: it does not span
        cantilever = not all(supported)
        field = means[:, :, along]  # (shells, case) the strip's moment, sagging positive
        keep = ~inside
        found = slab_design.strip_average(
            strip, centres[keep, along], centres[keep, 1 - along], field[keep], mesh, None,
            weights[keep],
        )  # fmt: skip
        if not found:
            continue
        middle = (strip.start + strip.end) / 2
        mid = min(found, key=lambda f: abs(f[0] - middle))[1] * 1e3  # N·mm/m
        ends: list[tuple[float, float]] = []
        if supported[0]:
            ends.append(tuple(-found[0][1] * 1e3))
        if supported[1]:
            ends.append(tuple(-found[-1][1] * 1e3))
        if cantilever and len(ends) != 1:
            continue
        a = strip.start - strip.before
        b = strip.end + strip.after
        within = (
            (node_local[:, 1 - along] >= strip.lo - 1.0)
            & (node_local[:, 1 - along] <= strip.hi + 1.0)
            & (node_local[:, along] >= min(a, b) - 1.0)
            & (node_local[:, along] <= max(a, b) + 1.0)
        )
        if not within.any():
            continue
        ref_a = reference(along, a, strip.lo, strip.hi) if supported[0] else None
        ref_b = reference(along, b, strip.lo, strip.hi) if supported[1] else None
        position = node_local[within, along]
        if ref_a is not None and ref_b is not None:
            share = ((position - a) / (b - a))[:, None] if b != a else np.zeros((len(position), 1))
            chord = (1 - share) * ref_a + share * ref_b
        else:
            ref = ref_a if ref_a is not None else ref_b
            if ref is None:
                continue
            chord = np.broadcast_to(ref, (len(position), 2))
        relative = u[within] - chord
        k = int(np.argmax(relative.sum(axis=1)))
        continuous = sum(
            1
            for other in context.strips
            if other is not strip
            and other.direction == strip.direction
            and abs(other.lo - strip.lo) <= 1.0
            and abs(other.hi - strip.hi) <= 1.0
            and (
                abs(other.end + other.after - a) <= 1.0
                or abs(other.start - other.before - b) <= 1.0
            )
        )
        spans.append(
            SpanData(
                strip.name,
                strip.direction,
                strip.kind,
                float(strip.span),
                cantilever,
                min(continuous, 2),
                (float(mid[0]), float(mid[1])),
                tuple((float(e[0]), float(e[1])) for e in ends),
                (float(relative[k, 0]), float(relative[k, 1])),
            )
        )
        regions.append((along, min(a, b), max(a, b), strip.lo, strip.hi))

    # Per shell: its deflection relative to the slab's supports and its mean moments.
    support_ref = u[on_support].mean(axis=0) if on_support.any() else np.zeros(2)
    index_of = {n: k for k, n in enumerate(ids)}
    out_shells: list[ShellData] = []
    for k, shell in enumerate(shells):
        own = [index_of[n] for n in node_ids.get(shell.id, ()) if n in index_of]
        if not own:
            continue
        centre = node_local[own].mean(axis=0)
        delta = u[own].mean(axis=0) - support_ref
        found = tuple(
            j
            for j, (along, a, b, lo, hi) in enumerate(regions)
            if a - 1.0 <= centre[along] <= b + 1.0 and lo - 1.0 <= centre[1 - along] <= hi + 1.0
        )
        m = means[k]  # (case, 5) N·m/m
        moments = tuple(float(v) * 1e3 for case in range(2) for v in m[case, :3])
        out_shells.append(
            ShellData(int(shell.id), (float(delta[0]), float(delta[1])), moments, found)
        )
    return SlabServiceData(
        slab_id,
        float(h),
        float(fc),
        float(fy),
        float(es),
        float(ec),
        float(ei),
        bool(roof),
        {
            name: (
                LayerData(float(layer.dia), float(layer.spacing), float(layer.d)) if layer else None
            )
            for name, layer in layers.items()
        },
        spans,
        out_shells,
    )

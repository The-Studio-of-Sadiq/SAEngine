"""Steel-concrete composite members under the code pack's ``composite`` table.

- composite beams: a steel I-beam acting with the slab (solid, or on formed steel deck with
  the ribs across or along the beam) through headed studs or channels: effective width, the
  connectors' strength (Rg, Rp), positive flexure by the plastic stress distribution (full or
  partial connection, the shear span from the analysis' moment diagram) or by the elastic
  stresses for a slender web, negative flexure on the steel alone or with the slab bars, the
  steel alone before the concrete hardens, the deck and stud rules, the connector spacing, the
  slab reinforcement and the effective inertia, creep and shrinkage of the deflections;
- composite columns: a steel shape encased in reinforced concrete or a concrete-filled HSS:
  the compressive strength (Po, EIeff, Pe), the tensile strength, the P-M interaction by the
  plastic stress distribution with the length effects, the load transfer between the steel
  and the concrete (studs or bearing), the scope limits and the detailing;
- composite connections: the rules of the force transfer (no bond, the seismic reduction of
  bearing, face bearing plates).

Every number comes from the table (``method`` names the generic implementation: the plastic
stress distribution); the clauses come from its ``sources``. Units: N, mm, MPa.

:func:`apply` adds the composite checks to a steel member's design report entry
(:func:`saengine.design.steel_design.design_member`); :func:`scale_profiles` and
:func:`adjust_deflection_rows` turn a steel beam's deflections into the composite beam's.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

TABLE = "composite"

#: The method lines of the design report when composite members were designed.
METHOD = [
    (
        "Composite members (when the beam or column type sets them), under the code pack's "
        "composite table: beams by the plastic stress distribution on the composite section (full "
        "or partial shear connection, the connectors between the largest positive moment and the "
        "nearest zero moment of the analysis), the steel alone for the negative moment unless the "
        "slab bars are given, the steel alone for the wet concrete when unshored; deflections with "
        "the effective inertia of partial connection, creep and shrinkage. Columns encased in "
        "concrete or concrete-filled HSS by the plastic stress distribution with the length effects "
        "of the effective stiffness; the load transfer between steel and concrete by studs or "
        "bearing; the code's detailing. Listed as 'Composite: ...' checks of the member; the steel "
        "alone checks the composite section replaces are kept as advisories."
    )
]


class CompositeError(ValueError):
    """The composite member cannot be checked (inputs outside what the clauses cover)."""


def composite_table() -> Any | None:
    """The ``composite`` table of the pack in force; None when it does not cover it."""
    try:
        from saengine.codes import context as code_context

        pack = code_context.current()
        return pack.table(TABLE) if pack.has(TABLE) else None
    except Exception:  # noqa: BLE001 - no pack machinery (a bare calculation)
        from saengine.codes.tables import builtin_table

        return builtin_table(TABLE)


def cite(table: Any, key: str) -> str:
    """The clause of ``key`` in the table's sources (its text before the page)."""
    return str(table.sources.get(key, "")).split(" (", 1)[0]


def _row(
    name: str,
    demand: float,
    capacity: float,
    unit: str,
    clause: str,
    note: str = "",
    combination: str | None = None,
    flag: bool = False,
    scale: float = 1.0,
    upper: bool = True,
) -> dict[str, Any]:
    """A check row like the steel member's: ``upper`` demand ≤ capacity, else demand ≥ it."""
    if upper:
        u = demand / capacity if capacity > 0 else (0.0 if demand <= 0 else 99.0)
    else:
        u = capacity / demand if demand > 0 else (0.0 if capacity <= 0 else 99.0)
    u = round(float(u), 3) if math.isfinite(u) else 99.0
    digits = 4 if not unit else 2  # ratios keep their small values
    return {
        "name": f"Composite: {name}",
        "demand": round(float(demand) / scale, digits),
        "capacity": round(float(capacity) / scale, digits),
        "unit": unit,
        "utilisation": u,
        "combination": combination,
        "ok": bool(u <= 1.0),
        "note": note,
        "flag": flag,
        "clause": clause,
    }


# ─────────────────────────────────────── concrete ───────────────────────────────────────


@dataclass(frozen=True)
class Concrete:
    fc: float  # used in the strength (capped at the table's limit)
    fc_given: float
    wc: float  # kg/m³, within the table's range
    ec: float  # MPa
    light: bool
    notes: tuple[str, ...] = ()


def concrete_modulus(fc: float, wc: float, table: Any) -> float:
    """Ec = coefficient × wc^exponent × √f'c (wc clamped to the table's range) [MPa]."""
    m = table.modulus
    w = min(max(wc, m.densityMin), m.densityMax)
    return float(m.concreteCoefficient) * w ** float(m.concreteExponent) * math.sqrt(fc)


def concrete_of(material: Any, table: Any, what: str = "concrete") -> Concrete:
    """The composite member's concrete from a 03 Materials concrete material."""
    props = getattr(material, "concrete", None)
    if props is None:
        raise CompositeError(f"{what} '{getattr(material, 'id', '?')}' is not a concrete")
    m = table.modulus
    notes: list[str] = []
    density = getattr(getattr(material, "mechanical", None), "density", None)
    if density is None:
        density = float(m.densityDefault)
        notes.append(f"wc = {density:g} kg/m³ (the material gives no density)")
    wc = min(max(float(density), m.densityMin), m.densityMax)
    light = wc < table.materials.lightweightBelow
    fc_max = table.materials.concreteMaxLight if light else table.materials.concreteMaxNormal
    fc = min(float(props.fc), float(fc_max))
    if fc < props.fc:
        notes.append(f"f'c = {props.fc:g} MPa used at {fc:g} MPa ({cite(table, 'materials')})")
    return Concrete(fc, float(props.fc), wc, concrete_modulus(fc, wc, table), light, tuple(notes))


def _fy(fy: float, table: Any, what: str, notes: list[str]) -> float:
    cap = float(table.materials.steelFyMax)
    if fy > cap:
        notes.append(f"{what} Fy {fy:g} MPa used at {cap:g} MPa ({cite(table, 'materials')})")
        return cap
    return fy


# ─────────────────────────────────── shear connectors ───────────────────────────────────


def stud_factors(deck: Any, per_row: int, e_mid: float | None, table: Any) -> tuple[float, float]:
    """(Rg, Rp) of headed studs: welded to the steel (``deck`` None), in the ribs of a deck
    across the beam or through a deck along it."""
    s = table.beam.studs
    if deck is None:
        return float(s.rgDirect), float(s.rpDirect)
    if deck.orientation == "perpendicular":
        rg = s.rgOne if per_row <= 1 else (s.rgTwo if per_row == 2 else s.rgThreeOrMore)
        strong = e_mid is not None and e_mid >= table.beam.deck.emidHt
        return float(rg), float(s.rpStrong if strong else s.rpWeak)
    wide = deck.ribWidth / deck.ribHeight >= table.beam.deck.ribRatio
    return float(s.rgParallelWide if wide else s.rgParallelNarrow), float(s.rpParallel)


def stud_strength(
    diameter: float, fu: float, concrete: Concrete, table: Any, rg: float = 1.0, rp: float = 1.0
) -> float:
    """Qn of one headed stud [N]: coefficient × Asc √(f'c Ec) ≤ Rg Rp Asc Fu."""
    asc = math.pi * diameter**2 / 4
    concrete_side = table.beam.studs.coefficient * asc * math.sqrt(concrete.fc * concrete.ec)
    return float(min(concrete_side, rg * rp * asc * fu))


def channel_strength(tf: float, tw: float, length: float, concrete: Concrete, table: Any) -> float:
    """Qn of one channel connector [N]: c (tf + share tw) Lc √(f'c Ec)."""
    c = table.beam.channel
    return float(
        c.coefficient * (tf + c.webShare * tw) * length * math.sqrt(concrete.fc * concrete.ec)
    )


# ─────────────────────────────────── composite beams ───────────────────────────────────


@dataclass
class _Layers:
    """Rectangles (top, bottom, width) measured down from the top of the slab [mm]."""

    rects: list[tuple[float, float, float]]

    def area(self, depth: float = math.inf) -> float:
        return sum(max(0.0, min(b, depth) - t) * w for t, b, w in self.rects)

    def moment(self, depth: float = math.inf) -> float:
        """First moment of area about the top over the given depth."""
        total = 0.0
        for t, b, w in self.rects:
            bottom = min(b, depth)
            if bottom > t:
                total += (bottom - t) * w * (t + bottom) / 2
        return total

    def depth_for(self, area: float) -> float:
        """The depth from the top whose area is ``area``."""
        done = 0.0
        for t, b, w in sorted(self.rects):
            piece = (b - t) * w
            if done + piece >= area:
                return t + (area - done) / w
            done += piece
        return max(b for _t, b, _w in self.rects)

    def inertia(self, about: float, depth: float = math.inf) -> float:
        total = 0.0
        for t, b, w in self.rects:
            bottom = min(b, depth)
            if bottom > t:
                h = bottom - t
                total += w * h**3 / 12 + w * h * ((t + bottom) / 2 - about) ** 2
        return total


@dataclass
class BeamGeometry:
    """A composite beam's section: slab layers and steel plates, from the top of the slab."""

    slab: _Layers
    steel: _Layers
    beff: float
    tc: float
    hr: float
    t_top: float
    d: float
    tf: float
    tw: float
    bf: float
    fy: float
    e: float
    notes: list[str] = field(default_factory=list)

    @property
    def steel_area(self) -> float:
        return self.steel.area()

    @property
    def steel_inertia(self) -> float:
        c = self.steel.moment() / self.steel.area()
        return self.steel.inertia(c)


def effective_width(span: float, beam: Any, table: Any) -> tuple[float, list[str]]:
    """The effective width of the slab [mm]: each side at most the span share, the spacing
    share of the distance to the next beam and the distance to the edge."""
    rules = table.beam
    notes = []
    total = 0.0
    for side, spacing, edge in (
        ("left", beam.spacingLeft, beam.edgeLeft),
        ("right", beam.spacingRight, beam.edgeRight),
    ):
        if spacing is None and edge is None:
            notes.append(f"no slab on the {side}: that side's effective width is 0")
            continue
        width = rules.spanShare * span
        if spacing is not None:
            width = min(width, rules.spacingShare * spacing)
        if edge is not None:
            width = min(width, edge)
        total += width
    return total, notes


def tributary_width(beam: Any) -> float:
    """The slab carried by the beam [mm]: half the spacing each side, or to the edge."""
    total = 0.0
    for spacing, edge in ((beam.spacingLeft, beam.edgeLeft), (beam.spacingRight, beam.edgeRight)):
        if spacing is not None:
            total += spacing / 2
        elif edge is not None:
            total += edge
    return total


def beam_geometry(shape: Any, fy: float, e: float, beam: Any, span: float, table: Any):
    """The :class:`BeamGeometry` of an I-shape under the beam's slab and deck."""
    if shape.family != "I":
        raise CompositeError(f"composite beams are I-shapes here, not {shape.family}")
    dims = shape.dims
    d, bf, tf, tw = dims["d"], dims["bf"], dims["tf"], dims["tw"]
    beff, notes = effective_width(span, beam, table)
    if beff <= 0:
        raise CompositeError("no slab: give the spacing to the next beams or the slab edges")
    deck = beam.deck
    hr = deck.ribHeight if deck is not None else 0.0
    tc = beam.slabThickness
    t_top = tc - hr
    if t_top <= 0:
        raise CompositeError("the slab is not thicker than the deck ribs")
    rects = [(0.0, t_top, beff)]
    if deck is not None and deck.orientation == "parallel":
        rects.append((t_top, tc, beff * min(1.0, deck.ribWidth / deck.ribPitch)))
    steel = [(tc, tc + tf, bf), (tc + tf, tc + d - tf, tw), (tc + d - tf, tc + d, bf)]
    notes.append("steel plates without the root fillets")
    return BeamGeometry(
        _Layers(rects), _Layers(steel), beff, tc, hr, t_top, d, tf, tw, bf, fy, e, notes
    )


def _steel_part(steel: _Layers, area: float, from_top: bool) -> tuple[float, float]:
    """(area, centroid depth) of the steel's first ``area`` from its top (or bottom)."""
    top = min(t for t, _b, _w in steel.rects)
    bottom = max(b for _t, b, _w in steel.rects)
    if from_top:
        y = steel.depth_for(area)
        a = steel.area(y)
        return a, steel.moment(y) / a if a > 0 else top
    flipped = _Layers([(bottom - b, bottom - t, w) for t, b, w in steel.rects])
    y = flipped.depth_for(area)
    a = flipped.area(y)
    centroid = flipped.moment(y) / a if a > 0 else 0.0
    return a, bottom - centroid


def plastic_positive(geom: BeamGeometry, fc: float, sum_qn: float, table: Any) -> dict[str, Any]:
    """The plastic positive moment [N·mm] with ``sum_qn`` of connection: C = min(0.85 f'c Ac,
    As Fy, ΣQn) in the slab, the rest of the steel split at the plastic neutral axis."""
    alpha = table.stressBlock.concrete
    ac = geom.slab.area()
    as_fy = geom.steel_area * geom.fy
    cc = alpha * fc * ac
    c = min(cc, as_fy, sum_qn)
    a = geom.slab.depth_for(c / (alpha * fc)) if c < cc else geom.slab.depth_for(ac)
    area_c = geom.slab.area(a)
    yc = geom.slab.moment(a) / area_c if area_c > 0 else 0.0
    cs = max(0.0, (as_fy - c) / 2)
    if cs > 1e-9:
        a_cs, y_cs = _steel_part(geom.steel, cs / geom.fy, from_top=True)
    else:
        a_cs, y_cs = 0.0, geom.tc
    ts = as_fy - cs
    # The tension part's centroid: the whole steel less the compression part.
    m_all = geom.steel.moment()
    y_t = (m_all - a_cs * y_cs) / max(geom.steel_area - a_cs, 1e-9)
    mn = ts * y_t - c * yc - cs * y_cs
    governs = "concrete" if c == cc else ("steel" if c == as_fy else "connectors")
    full = min(cc, as_fy)
    return {
        "Mn": mn,
        "C": c,
        "a": a,
        "full": full,
        "ratio": min(1.0, sum_qn / full) if full > 0 else 1.0,
        "governs": governs,
    }


def plastic_negative(geom: BeamGeometry, t_bars: float, bar_depth: float) -> float:
    """The plastic negative moment [N·mm] with the slab bars' force ``t_bars`` at
    ``bar_depth`` from the top: the steel's compression from its bottom."""
    as_fy = geom.steel_area * geom.fy
    c_steel = (as_fy + t_bars) / 2
    a_c, y_c = _steel_part(geom.steel, c_steel / geom.fy, from_top=False)
    t_steel = as_fy - c_steel
    m_all = geom.steel.moment()
    y_t = (m_all - a_c * y_c) / max(geom.steel_area - a_c, 1e-9)
    return c_steel * y_c - t_steel * y_t - t_bars * bar_depth


def transformed(geom: BeamGeometry, n: float) -> tuple[float, float]:
    """(It, neutral axis depth from the top) of the section transformed by n = Es/Ec, the
    concrete below the neutral axis left out."""
    depth = math.inf
    for _ in range(50):
        a_c = geom.slab.area(depth) / n
        a_s = geom.steel_area
        y = (geom.slab.moment(depth) / n + geom.steel.moment()) / (a_c + a_s)
        if abs(min(y, geom.tc) - min(depth, geom.tc)) < 1e-6:
            break
        depth = y
    it = geom.slab.inertia(y, depth) / n + geom.steel.inertia(y)
    return it, y


def effective_inertia(is_: float, it: float, ratio: float, table: Any) -> float:
    """Ie = Is + c p^e (It - Is): partial shear connection and slip."""
    r = table.beam.deflection
    return is_ + r.coefficient * max(0.0, min(1.0, ratio)) ** r.exponent * (it - is_)


def shear_span(st: Any) -> tuple[float, float, int]:
    """(largest positive moment [N·mm], the shorter distance from it to zero moment or the
    member's end [mm], its station) of one combination's stations."""
    sag = -np.asarray(st.Mx, dtype=float)
    s = np.asarray(st.s, dtype=float) * 1000.0
    i = int(np.argmax(sag))
    peak = float(sag[i])
    if peak <= 0:
        return 0.0, 0.0, i

    def reach(step: int) -> float:
        j = i
        while 0 <= j + step < len(s):
            k = j + step
            if sag[k] <= 0:
                frac = sag[j] / (sag[j] - sag[k]) if sag[j] != sag[k] else 0.0
                return abs(s[j] + frac * (s[k] - s[j]) - s[i])
            j = k
        return abs(s[j] - s[i])

    return peak, min(reach(-1), reach(1)), i


@dataclass
class _Connectors:
    qn: float  # one connector
    per_row: int
    rg: float
    rp: float
    kind: str
    diameter: float

    def row(self) -> float:
        return self.qn * self.per_row


def _connectors(beam: Any, concrete: Concrete, table: Any) -> _Connectors:
    c = beam.connectors
    if c.kind == "channel":
        qn = channel_strength(c.channelFlange, c.channelWeb, c.channelLength, concrete, table)
        return _Connectors(qn, c.perRow, 1.0, 1.0, "channel", 0.0)
    rg, rp = stud_factors(beam.deck, c.perRow, c.eMidHeight, table)
    return _Connectors(
        stud_strength(c.diameter, c.fu, concrete, table, rg, rp),
        c.perRow,
        rg,
        rp,
        "stud",
        c.diameter,
    )


def _spacing_limits(beam: Any, table: Any) -> tuple[float, float, float]:
    """(least spacing, largest spacing, step) of the connector rows along the beam [mm]."""
    sp = table.beam.spacing
    d = beam.connectors.diameter if beam.connectors.kind == "stud" else 0.0
    deck = beam.deck
    if deck is not None and deck.orientation == "perpendicular":
        least = max(sp.ribs * d, deck.ribPitch)
        step = deck.ribPitch
    else:
        step = 25.0
        least = sp.longitudinal * d if d else step
    largest = min(sp.slabMultiple * beam.slabThickness, sp.max)
    return least, largest, step


def _bar_depth(geom: BeamGeometry) -> float:
    return geom.t_top / 2


def beam_checks(
    shape: Any,
    material: Any,
    concrete_material: Any,
    beam: Any,
    stations: list[Any],
    span_m: float,
    steel_flexure: dict[str, Any] | None,
    table: Any,
) -> dict[str, Any]:
    """The composite beam's checks and summary: ``{"checks", "summary", "notes", "deflection"}``.
    ``steel_flexure``: the steel member's major-axis flexure row (its design capacity is the
    steel alone's, with the member's own bracing)."""
    from saengine.design.steel import classify as cl
    from saengine.design.steel.members import Steel

    steel = Steel.of(material)
    notes: list[str] = []
    fy = _fy(steel.fy, table, "steel", notes)
    concrete = concrete_of(concrete_material, table, "slab concrete")
    notes += list(concrete.notes)
    span = span_m * 1000.0
    geom = beam_geometry(shape, fy, steel.e, beam, span, table)
    notes += geom.notes
    phi = table.phi.flexure
    checks: list[dict[str, Any]] = []
    conn = _connectors(beam, concrete, table)

    # Concrete strength within the code's range.
    if concrete.fc_given < table.materials.concreteMin:
        checks.append(
            _row(
                "slab concrete f'c",
                concrete.fc_given,
                table.materials.concreteMin,
                "MPa",
                cite(table, "materials"),
                upper=False,
            )
        )

    # Positive flexure: plastic (compact web) or elastic (slender web).
    rows = [(st, *shear_span(st)) for st in stations]
    rows = [r for r in rows if r[1] > 0]
    h_tw = shape.dims["h"] / shape.dims["tw"]
    plastic = h_tw <= table.beam.webCompact * math.sqrt(steel.e / fy)
    least, largest, step = _spacing_limits(beam, table)
    spacing = beam.connectors.spacing
    designed = spacing is None
    wet = _wet_load(beam, shape, material, concrete.wc)
    m_pre = 0.0 if beam.shored else table.beam.constructionDeadFactor * wet[0] * span**2 / 8

    def capacity(row: Any, s: float) -> tuple[float, dict[str, Any]]:
        n_rows = math.floor(row[2] / s + 1e-9)
        sum_qn = n_rows * conn.row()
        if plastic:
            found = plastic_positive(geom, concrete.fc, sum_qn, table)
        else:
            found = _elastic_positive(geom, concrete, m_pre, table)
            found["ratio"] = 1.0
        found["rows"] = n_rows
        found["sumQn"] = sum_qn
        return phi * found["Mn"], found

    if designed:
        candidates = []
        s = largest - (largest % step if step else 0)
        while s >= least - 1e-9:
            candidates.append(s)
            s -= step
        spacing = candidates[-1] if candidates else least
        for s in candidates:
            if all(capacity(r, s)[0] >= r[1] for r in rows):
                spacing = s
                break
    governing: tuple[float, dict[str, Any], Any] | None = None
    for r in rows:
        cap, found = capacity(r, spacing)
        u = r[1] / cap if cap > 0 else math.inf
        if governing is None or u > governing[0]:
            governing = (u, found, r)
    summary: dict[str, Any] = {
        "effectiveWidth": round(geom.beff, 0),
        "connector": conn.kind,
        "qn": round(conn.qn / 1e3, 2),
        "rg": conn.rg,
        "rp": conn.rp,
        "perRow": conn.per_row,
        "spacing": round(spacing, 0),
        "designedSpacing": designed,
        "rows": math.floor(span / spacing + 1e-9) if spacing > 0 else 0,
        "method": "plastic" if plastic else "elastic",
    }
    summary["connectors"] = summary["rows"] * conn.per_row
    if governing is not None:
        u, found, r = governing
        cap = phi * found["Mn"]
        method_note = (
            f"plastic, C = {found['C'] / 1e3:.0f} kN ({found['governs']}), "
            f"ΣQn = {found['sumQn'] / 1e3:.0f} kN over {r[2]:.0f} mm, "
            f"{found['ratio']:.0%} of full connection"
            if plastic
            else f"elastic yield moment (h/tw = {h_tw:.0f} slender), "
            f"{'shored' if beam.shored else 'unshored'}"
        )
        checks.append(
            _row(
                "positive flexure",
                r[1],
                cap,
                "kN·m",
                cite(table, "positiveFlexure"),
                f"{method_note}; beff = {geom.beff:.0f} mm",
                r[0].combination,
                scale=1e6,
            )
        )
        summary["ratio"] = round(found["ratio"], 3)
        summary["sumQn"] = round(found["sumQn"] / 1e3, 1)
        summary["Mn"] = round(found["Mn"] / 1e6, 1)
    else:
        summary["ratio"] = 1.0

    # Negative flexure: the steel alone, or with the developed slab bars.
    hog = [(st, float(np.max(np.asarray(st.Mx, dtype=float)))) for st in stations]
    hog = [h for h in hog if h[1] > 0]
    if hog:
        st, mu = max(hog, key=lambda h: h[1])
        steel_cap = (steel_flexure or {}).get("capacity", 0.0) * 1e6
        cap, note = steel_cap, "the steel alone (its flexure check)"
        braced = steel_cap >= 0.999 * phi * fy * shape.zx
        compact = cl.section_class(cl.flexure_elements(shape, fy, steel.e, "x")) == cl.COMPACT
        if beam.slabBars and braced and compact:
            sum_qn = math.floor(summary["rows"] / 2) * conn.row()
            t_bars = min(beam.slabBars * beam.slabBarFy, sum_qn)
            mn = plastic_negative(geom, t_bars, _bar_depth(geom))
            if phi * mn > cap:
                cap = phi * mn
                note = (
                    f"plastic with the slab bars: T = min(Ar Fyr, ΣQn) = {t_bars / 1e3:.0f} kN "
                    f"({cite(table, 'negativeTransfer')}; ΣQn {sum_qn / 1e3:.0f} kN)"
                )
        elif beam.slabBars:
            note += "; the slab bars are not counted: the steel is not compact and fully braced"
        checks.append(
            _row(
                "negative flexure",
                mu,
                cap,
                "kN·m",
                cite(table, "negativeFlexure"),
                note,
                st.combination,
                scale=1e6,
            )
        )

    # The steel alone before the concrete hardens (unshored).
    if not beam.shored and steel_flexure is not None:
        w_d, w_l = wet
        mu = (
            (table.beam.constructionDeadFactor * w_d + table.beam.constructionLiveFactor * w_l)
            * span**2
            / 8
        )
        note = (
            f"wet concrete, deck and beam {w_d:.2f} N/mm"
            + (f", erection load {w_l:.2f} N/mm" if w_l else ", no erection load given")
            + f"; simply supported; until f'c reaches {table.beam.constructionStrength:.0%}"
        )
        checks.append(
            _row(
                "construction stage (steel alone)",
                mu,
                steel_flexure["capacity"] * 1e6,
                "kN·m",
                cite(table, "construction"),
                note,
                scale=1e6,
            )
        )

    checks += _beam_detailing(beam, geom, spacing, least, largest, table)

    # Deflection: the effective inertia (partial connection, slip), creep, shrinkage.
    n = steel.e / concrete.ec
    it, _y = transformed(geom, n)
    is_ = geom.steel_inertia
    ie = effective_inertia(is_, it, summary["ratio"], table)
    deflection = {
        "Is": is_,
        "Ie": ie,
        "stiffening": is_ / ie if ie > 0 else 1.0,
        "creep": float(table.beam.deflection.creep),
        "shored": beam.shored,
        "sustained": beam.sustainedLive,
        "shrinkage": None,
        "clause": cite(table, "deflection"),
    }
    if beam.shrinkage is not None:
        deflection["shrinkage"] = shrinkage_deflection(
            geom, steel.e, concrete, beam.shrinkage, summary["ratio"], span, table
        )
    summary["Ie"] = round(ie / 1e6, 1)
    summary["It"] = round(it / 1e6, 1)
    summary["Is"] = round(is_ / 1e6, 1)
    return {"checks": checks, "summary": summary, "notes": notes, "deflection": deflection}


def _wet_load(beam: Any, shape: Any, material: Any, wc: float) -> tuple[float, float]:
    """(dead, erection) line loads on the beam before the concrete hardens [N/mm]; ``wc``
    the concrete's density [kg/m³]."""
    trib = tributary_width(beam)
    deck = beam.deck
    t_eq = beam.slabThickness
    deck_weight = 0.0
    if deck is not None:
        t_eq = beam.slabThickness - deck.ribHeight * (1 - min(1.0, deck.ribWidth / deck.ribPitch))
        deck_weight = deck.weight * 1e-3
    g = 9.81e-9  # N per kg × m³ per mm³
    density = getattr(getattr(material, "mechanical", None), "density", None) or 7850.0
    slab = wc * g * t_eq
    return (
        slab + deck_weight
    ) * trib + density * g * shape.area, beam.constructionLive * 1e-3 * trib


def _elastic_positive(
    geom: BeamGeometry, concrete: Concrete, m_pre: float, table: Any
) -> dict[str, Any]:
    """The yield moment of the composite section [N·mm], the moment before composite action
    ``m_pre`` on the steel alone (unshored)."""
    n = geom.e / concrete.ec
    it, y = transformed(geom, n)
    bottom = geom.tc + geom.d
    s_tr = it / (bottom - y)
    c = geom.steel.moment() / geom.steel_area
    s_steel = geom.steel_inertia / (bottom - c)
    f_pre = m_pre / s_steel
    mn = m_pre + max(0.0, geom.fy - f_pre) * s_tr
    return {"Mn": mn, "C": 0.0, "a": 0.0, "full": 0.0, "governs": "steel"}


def shrinkage_deflection(
    geom: BeamGeometry,
    e: float,
    concrete: Concrete,
    data: Any,
    ratio: float,
    span: float,
    table: Any,
) -> dict[str, float]:
    """Δs = L²/8 × c εf Ac y / (ns Ies) of a simply supported beam [mm], E'c = Ec / (1 + χφ)."""
    ec_age = concrete.ec / (1 + data.aging * data.creep)
    ns = e / ec_age
    its, y_na = transformed(geom, ns)
    ies = effective_inertia(geom.steel_inertia, its, ratio, table)
    ac = geom.slab.area(min(y_na, geom.tc))
    y_slab = geom.slab.moment(min(y_na, geom.tc)) / ac if ac > 0 else 0.0
    y = y_na - y_slab
    delta = span**2 / 8 * data.coefficient * data.freeStrain * ac * y / (ns * ies)
    return {"delta": float(delta), "ns": ns, "Ies": ies}


def _beam_detailing(
    beam: Any, geom: BeamGeometry, spacing: float, least: float, largest: float, table: Any
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    c = beam.connectors
    deck = beam.deck
    rules = table.beam
    dk = rules.deck
    if c.kind == "stud":
        rows.append(
            _row(
                "stud length",
                c.height,
                rules.studs.lengthMin * c.diameter,
                "mm",
                cite(table, "shearConnectors"),
                f"at least {rules.studs.lengthMin:g} diameters",
                upper=False,
            )
        )
        if not c.overWeb:
            rows.append(
                _row(
                    "stud diameter off the web",
                    c.diameter,
                    rules.spacing.flangeRatio * geom.tf,
                    "mm",
                    cite(table, "studSpacing"),
                    f"at most {rules.spacing.flangeRatio:g} × the flange thickness",
                )
            )
        if c.perRow > 1 and c.transverseSpacing is not None:
            across = (
                rules.spacing.ribs
                if deck and deck.orientation == "perpendicular"
                else (rules.spacing.transverse)
            )
            rows.append(
                _row(
                    "stud spacing across the beam",
                    c.transverseSpacing,
                    across * c.diameter,
                    "mm",
                    cite(table, "studSpacing"),
                    upper=False,
                )
            )
    rows.append(
        _row(
            "connector spacing (least)",
            spacing,
            least,
            "mm",
            cite(table, "studSpacing"),
            "designed" if beam.connectors.spacing is None else "given",
            upper=False,
        )
    )
    rows.append(
        _row(
            "connector spacing (largest)",
            spacing,
            largest,
            "mm",
            cite(table, "studSpacing"),
            f"at most {rules.spacing.slabMultiple:g} × the slab and {rules.spacing.max:g} mm",
        )
    )
    if deck is not None:
        clause = cite(table, "deck")
        rows.append(_row("deck rib height", deck.ribHeight, dk.ribHeightMax, "mm", clause))
        rows.append(
            _row("deck rib width", deck.ribWidth, dk.ribWidthMin, "mm", clause, upper=False)
        )
        rows.append(
            _row("slab above the deck", geom.t_top, dk.slabAboveDeck, "mm", clause, upper=False)
        )
        if c.kind == "stud":
            rows.append(_row("stud diameter", c.diameter, dk.studDiameterMax, "mm", clause))
            rows.append(
                _row(
                    "stud above the deck",
                    c.height - deck.ribHeight,
                    dk.studAboveDeck,
                    "mm",
                    clause,
                    upper=False,
                )
            )
            rows.append(
                _row(
                    "cover above the studs",
                    beam.slabThickness - c.height,
                    dk.studCover,
                    "mm",
                    clause,
                    upper=False,
                )
            )
            if deck.orientation == "parallel" and deck.ribHeight >= dk.haunchDepth:
                need = dk.haunchWidthFirst + dk.haunchWidthPerStud * c.diameter * (c.perRow - 1)
                rows.append(
                    _row(
                        "haunch width for the studs",
                        deck.ribWidth,
                        need,
                        "mm",
                        cite(table, "deckParallel"),
                        upper=False,
                    )
                )
        if deck.anchorageSpacing is not None:
            rows.append(
                _row(
                    "deck anchorage spacing",
                    deck.anchorageSpacing,
                    dk.anchorageSpacing,
                    "mm",
                    clause,
                )
            )
        else:
            rows.append(
                _row(
                    "deck anchorage spacing",
                    dk.anchorageSpacing,
                    dk.anchorageSpacing,
                    "mm",
                    clause,
                    "anchor the deck to every support at these centres at most (studs or "
                    "puddle welds)",
                    flag=True,
                )
            )
    # Slab reinforcement across the beam (per metre of beam) and at the beam ends.
    slab = rules.slab
    if deck is None:
        share = slab.transverseOnDeck
        area = beam.slabThickness * 1000.0
    elif deck.orientation == "parallel":
        share, area = slab.transverseParallel, geom.t_top * 1000.0
    else:
        share, area = slab.transversePerpendicular, geom.t_top * 1000.0
    need = share * area
    rows.append(
        _row(
            "transverse slab bars",
            need,
            need,
            "mm²/m",
            cite(table, "slabReinforcement"),
            f"at least {share:g} × the concrete, in the lower part of the slab, developed",
            flag=True,
        )
    )
    if deck is not None and deck.orientation == "perpendicular":
        rows.append(
            _row(
                "bars at the beam ends",
                slab.endBars,
                slab.endBars,
                "bars",
                cite(table, "slabReinforcement"),
                f"at least {slab.endBars:g} bars of {slab.endBarDiameter:g} mm or equivalent",
                flag=True,
            )
        )
    return rows


def scale_profiles(entry: dict[str, Any], profiles: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """A composite beam's displacements per load case from the steel beam's (the analysis
    carries the steel section): the cases on the composite section × Is/Ie, the dead load ×
    Is/Ie only when shored (else on the steel alone), the dead and long-term live loads
    increased for creep. Unchanged for other members."""
    found = (entry.get("composite") or {}).get("deflection")
    if not found:
        return profiles
    k = found["stiffening"]
    creep = found["creep"]
    out = {}
    for case, moved in profiles.items():
        if case == "D":
            factor = k * (1 + creep) if found["shored"] else 1.0
        elif case == "L":
            factor = k * (1 + creep * found["sustained"])
        else:
            factor = k
        out[case] = moved * factor
    return out


def adjust_deflection_rows(entry: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict]:
    """The composite beam's deflection rows: the clause and the effective inertia in the notes,
    and the shrinkage deflection added to the long-term (dead + live) rows."""
    found = (entry.get("composite") or {}).get("deflection")
    if not found:
        return rows
    shrink = (found.get("shrinkage") or {}).get("delta", 0.0)
    for row in rows:
        row["note"] = (
            f"{row['note']}; composite: Ie = {found['Ie'] / 1e6:.0f}e6 mm⁴ "
            f"(Is {found['Is'] / 1e6:.0f}e6), creep +{found['creep']:.0%}"
        )
        row["clause"] = (
            f"{row['clause']}; {found['clause']}" if row.get("clause") else (found["clause"])
        )
        if shrink and "dead + live" in row["name"]:
            row["demand"] = round(row["demand"] + shrink, 2)
            cap = row["capacity"]
            u = row["demand"] / cap if cap > 0 else 99.0
            row["utilisation"] = round(u, 3)
            row["ok"] = bool(u <= 1.0)
            row["note"] += f"; with {shrink:.1f} mm of shrinkage"
    return rows


# ─────────────────────────────────── composite columns ───────────────────────────────────


@dataclass
class Fibers:
    """The section as fibers: centroids x, y [mm], areas [mm²] and kinds (steel, bar,
    concrete, and the concrete displaced by steel or bars, 'void')."""

    x: np.ndarray
    y: np.ndarray
    a: np.ndarray
    kind: np.ndarray

    @staticmethod
    def join(parts: list[Fibers]) -> Fibers:
        return Fibers(
            np.concatenate([p.x for p in parts]),
            np.concatenate([p.y for p in parts]),
            np.concatenate([p.a for p in parts]),
            np.concatenate([p.kind for p in parts]),
        )


def _rect(x0: float, x1: float, y0: float, y1: float, kind: str, n: int = 24) -> Fibers:
    nx = max(1, int(n * (x1 - x0) / max(x1 - x0, y1 - y0)))
    ny = max(1, int(n * (y1 - y0) / max(x1 - x0, y1 - y0)))
    xs = x0 + (np.arange(nx) + 0.5) * (x1 - x0) / nx
    ys = y0 + (np.arange(ny) + 0.5) * (y1 - y0) / ny
    gx, gy = np.meshgrid(xs, ys)
    area = (x1 - x0) * (y1 - y0) / (nx * ny)
    count = gx.size
    return Fibers(gx.ravel(), gy.ravel(), np.full(count, area), np.full(count, kind))


def _ring(r0: float, r1: float, kind: str, nr: int, nt: int = 72) -> Fibers:
    rs = np.linspace(r0, r1, nr + 1)
    mid = (rs[:-1] + rs[1:]) / 2
    ts = (np.arange(nt) + 0.5) * 2 * math.pi / nt
    gr, gt = np.meshgrid(mid, ts)
    areas = np.repeat(((rs[1:] ** 2 - rs[:-1] ** 2) * math.pi / nt)[None, :], nt, axis=0)
    return Fibers(
        (gr * np.cos(gt)).ravel(),
        (gr * np.sin(gt)).ravel(),
        areas.ravel(),
        np.full(gr.size, kind),
    )


def bar_positions(col: Any) -> list[tuple[float, float]]:
    """The encased column's bars: one at each corner, the rest spread over the sides."""
    if col.bars <= 0:
        return []
    off = col.cover + col.tieDiameter + col.barDiameter / 2
    x, y = col.width / 2 - off, col.depth / 2 - off
    pts = [(-x, -y), (x, -y), (x, y), (-x, y)][: col.bars]
    extra = max(0, col.bars - 4)
    sides = [0, 0, 0, 0]  # top, bottom, left, right
    for i in range(extra):
        sides[i % 4] += 1
    for k in range(sides[0]):
        pts.append((-x + 2 * x * (k + 1) / (sides[0] + 1), y))
    for k in range(sides[1]):
        pts.append((-x + 2 * x * (k + 1) / (sides[1] + 1), -y))
    for k in range(sides[2]):
        pts.append((-x, -y + 2 * y * (k + 1) / (sides[2] + 1)))
    for k in range(sides[3]):
        pts.append((x, -y + 2 * y * (k + 1) / (sides[3] + 1)))
    return pts


@dataclass
class ColumnSection:
    form: str
    fibers: Fibers
    alpha: float  # concrete stress / f'c
    as_: float
    asr: float
    ac: float
    ag: float
    is_: dict[str, float]
    isr: dict[str, float]
    ic: dict[str, float]
    c_stiff: float  # C1 or C3
    bar_share: float  # of Es Isr in EIeff
    least: float
    greatest: float
    bars: list[tuple[float, float]]


def column_section(shape: Any, col: Any, fyr: float, table: Any) -> ColumnSection:
    """The composite column's fibers and areas: an I-shape encased in a rectangle of concrete
    with bars, or a rectangular or round HSS filled with concrete."""
    rules = table.column
    d = shape.dims
    parts: list[Fibers] = []
    bars: list[tuple[float, float]] = []
    if col.form == "encased":
        if shape.family != "I":
            raise CompositeError(f"encased columns are I-shapes here, not {shape.family}")
        dd, bf, tf, tw = d["d"], d["bf"], d["tf"], d["tw"]
        if bf >= col.width or dd >= col.depth:
            raise CompositeError("the steel shape does not fit in the concrete")
        steel = [
            _rect(-bf / 2, bf / 2, dd / 2 - tf, dd / 2, "steel"),
            _rect(-bf / 2, bf / 2, -dd / 2, -dd / 2 + tf, "steel"),
            _rect(-tw / 2, tw / 2, -dd / 2 + tf, dd / 2 - tf, "steel"),
        ]
        parts += steel
        parts += [
            Fibers(s.x, s.y, s.a, np.full(s.a.size, "void")) for s in steel
        ]  # the concrete the steel displaces
        parts.append(
            _rect(-col.width / 2, col.width / 2, -col.depth / 2, col.depth / 2, "concrete", 40)
        )
        bars = bar_positions(col)
        abar = math.pi * col.barDiameter**2 / 4
        if bars:
            bx = np.array([p[0] for p in bars])
            by = np.array([p[1] for p in bars])
            parts.append(Fibers(bx, by, np.full(len(bars), abar), np.full(len(bars), "bar")))
            parts.append(Fibers(bx, by, np.full(len(bars), abar), np.full(len(bars), "void")))
        alpha = table.stressBlock.concrete
        ag = col.width * col.depth
        as_ = 2 * bf * tf + (dd - 2 * tf) * tw
        asr = abar * len(bars)
        ac = ag - as_ - asr
        isx = shape.ix
        isy = shape.iy
        isr = {
            "x": sum(abar * p[1] ** 2 for p in bars),
            "y": sum(abar * p[0] ** 2 for p in bars),
        }
        ic = {
            "x": col.width * col.depth**3 / 12 - isx - isr["x"],
            "y": col.depth * col.width**3 / 12 - isy - isr["y"],
        }
        e = rules.encased
        c_stiff = min(e.c1Base + e.c1Slope * as_ / (ac + as_), e.c1Max)
        share = e.barStiffnessShare
        least, greatest = min(col.width, col.depth), max(col.width, col.depth)
    elif col.form == "filled" and shape.family == "rhs":
        big_b, big_h, t = d["B"], d["H"], d["t"]
        parts += [
            _rect(-big_b / 2, big_b / 2, big_h / 2 - t, big_h / 2, "steel"),
            _rect(-big_b / 2, big_b / 2, -big_h / 2, -big_h / 2 + t, "steel"),
            _rect(-big_b / 2, -big_b / 2 + t, -big_h / 2 + t, big_h / 2 - t, "steel"),
            _rect(big_b / 2 - t, big_b / 2, -big_h / 2 + t, big_h / 2 - t, "steel"),
            _rect(-big_b / 2 + t, big_b / 2 - t, -big_h / 2 + t, big_h / 2 - t, "concrete", 40),
        ]
        alpha = rules.filled.c2Rectangular
        as_ = shape.area
        bi, hi = big_b - 2 * t, big_h - 2 * t
        ac = bi * hi
        ag = big_b * big_h
        asr = 0.0
        isx, isy = shape.ix, shape.iy
        isr = {"x": 0.0, "y": 0.0}
        ic = {"x": bi * hi**3 / 12, "y": hi * bi**3 / 12}
        f = rules.filled
        c_stiff = min(f.c3Base + f.c3Slope * as_ / (ac + as_), f.c3Max)
        share = 1.0
        least, greatest = min(big_b, big_h), max(big_b, big_h)
    elif col.form == "filled" and shape.family == "chs":
        dia, t = d["D"], d["t"]
        ri = dia / 2 - t
        parts += [_ring(ri, dia / 2, "steel", 3), _ring(0.0, ri, "concrete", 20)]
        alpha = rules.filled.c2Circular
        as_ = shape.area
        ac = math.pi * ri**2
        ag = math.pi * dia**2 / 4
        asr = 0.0
        isx = isy = shape.ix
        isr = {"x": 0.0, "y": 0.0}
        ic = {"x": math.pi * ri**4 / 4, "y": math.pi * ri**4 / 4}
        f = rules.filled
        c_stiff = min(f.c3Base + f.c3Slope * as_ / (ac + as_), f.c3Max)
        share = 1.0
        least = greatest = dia
    else:
        raise CompositeError(
            f"a filled column needs a rectangular or round HSS, not {shape.family}"
        )
    return ColumnSection(
        col.form,
        Fibers.join(parts),
        float(alpha),
        as_,
        asr,
        ac,
        ag,
        {"x": isx, "y": isy},
        isr,
        ic,
        c_stiff,
        share,
        least,
        greatest,
        bars,
    )


def plastic_curve(
    sec: ColumnSection, fy: float, fyr: float, fc: float, axis: str, steps: int = 120
) -> tuple[np.ndarray, np.ndarray]:
    """The nominal P-M curve [N, N·mm] about ``axis`` ("x": bending about x, the fibers' y)
    by the plastic stress distribution: from all in compression to all in tension, the
    moment positive (compression on the + side)."""
    f = sec.fibers
    coord = f.y if axis == "x" else f.x
    stress_c = np.select(
        [f.kind == "steel", f.kind == "bar", f.kind == "concrete", f.kind == "void"],
        [fy, fyr, sec.alpha * fc, -sec.alpha * fc],
    )
    stress_t = np.select([f.kind == "steel", f.kind == "bar"], [-fy, -fyr], 0.0)
    top, bottom = float(coord.max()), float(coord.min())
    # The neutral axis from below the section (all in compression) to above it (all tension).
    levels = np.concatenate([[bottom - 1.0], np.linspace(bottom, top, steps), [top + 1.0]])
    above = coord[None, :] > levels[:, None]
    stress = np.where(above, stress_c[None, :], stress_t[None, :])
    force = stress * f.a[None, :]
    p = force.sum(axis=1)
    m = (force * coord[None, :]).sum(axis=1)
    return p, np.abs(m)


def effective_stiffness(sec: ColumnSection, ec: float, es: float, axis: str) -> float:
    """EIeff = Es Is + share Es Isr + C Ec Ic [N·mm²]."""
    return es * sec.is_[axis] + sec.bar_share * es * sec.isr[axis] + sec.c_stiff * ec * sec.ic[axis]


def axial_strength(po: float, pe: float, table: Any) -> float:
    """Pn of the flexural buckling: Po × base^(Po/Pe) when Pe ≥ ratio Po, else elastic × Pe."""
    b = table.column.buckling
    if pe >= b.ratio * po:
        return po * b.base ** (po / pe)
    return b.elastic * pe


def _capacity_at(p_d: np.ndarray, m_d: np.ndarray, pu: float) -> float:
    order = np.argsort(p_d)
    return float(np.interp(pu, p_d[order], m_d[order]))


def column_checks(
    shape: Any,
    material: Any,
    concrete_material: Any,
    col: Any,
    stations: list[Any],
    lengths: Any,
    seismic: bool,
    table: Any,
) -> dict[str, Any]:
    """The composite column's checks and summary: ``{"checks", "summary", "notes"}``."""
    from saengine.design.steel import classify as cl
    from saengine.design.steel.members import Steel, amplifier_b1, moment_coefficient

    steel = Steel.of(material)
    notes: list[str] = []
    fy = _fy(steel.fy, table, "steel", notes)
    fyr = _fy(col.barFy, table, "bar", notes) if col.form == "encased" else 0.0
    concrete = concrete_of(concrete_material, table, "column concrete")
    notes += list(concrete.notes)
    if col.form == "filled" and col.bars:
        notes.append("bars inside the HSS are not counted")
    sec = column_section(shape, col, fyr, table)
    es = float(table.modulus.steel)
    fc = concrete.fc
    checks: list[dict[str, Any]] = []
    po = sec.as_ * fy + sec.asr * fyr + sec.alpha * sec.ac * fc
    length = lengths.length * 1000.0
    pe, kl = {}, {}
    for axis in ("x", "y"):
        seg = getattr(lengths, axis)
        kl[axis] = float(lengths.k.get(axis, 1.0)) * seg.longest() * 1000.0
        ei = effective_stiffness(sec, concrete.ec, es, axis)
        pe[axis] = math.pi**2 * ei / kl[axis] ** 2 if kl[axis] > 0 else math.inf
    pe_min = min(pe.values())
    pn = axial_strength(po, pe_min, table)
    lam = pn / po if po > 0 else 1.0
    phi_c, phi_t, phi_b = table.phi.compression, table.phi.tension, table.phi.flexure
    pnt = sec.as_ * fy + sec.asr * fyr
    key = "encased" if col.form == "encased" else "filled"
    curves = {}
    for axis in ("x", "y"):
        p, m = plastic_curve(sec, fy, fyr, fc, axis)
        p_d = np.where(p > 0, phi_c * lam * p, phi_t * p)
        curves[axis] = (p_d, phi_b * m)

    worst_c = worst_t = worst_i = None
    for st in stations:
        P = np.asarray(st.P, dtype=float)
        mx = np.asarray(st.Mx, dtype=float)
        my = np.asarray(st.My, dtype=float)
        s = np.asarray(st.s, dtype=float)
        pu = float(P.max())
        tu = float(-P.min())
        if pu > 0:
            u = pu / (phi_c * pn)
            if worst_c is None or u > worst_c[0]:
                worst_c = (u, pu, st.combination)
        if tu > 0:
            u = tu / (phi_t * pnt)
            if worst_t is None or u > worst_t[0]:
                worst_t = (u, tu, st.combination)
        # The interaction at every station, the moments amplified for the member's buckling.
        b1 = {}
        for axis, mm in (("x", mx), ("y", my)):
            cm = moment_coefficient(s, mm, float(s[0]), float(s[-1])) if len(s) > 1 else 1.0
            ei = effective_stiffness(sec, concrete.ec, es, axis)
            pe1 = math.pi**2 * ei / (length**2) if length > 0 else math.inf
            b1[axis] = amplifier_b1(cm, max(pu, 0.0), pe1)
        for k in range(len(P)):
            demand_p = float(P[k])
            parts = []
            for axis, mm in (("x", mx), ("y", my)):
                mu = abs(float(mm[k])) * (b1[axis] if demand_p > 0 else 1.0)
                if mu <= 0:
                    continue
                p_d, m_d = curves[axis]
                if demand_p > p_d.max() or demand_p < p_d.min():
                    parts.append(math.inf)
                    continue
                cap = _capacity_at(p_d, m_d, demand_p)
                parts.append(mu / cap if cap > 0 else math.inf)
            if demand_p > 0:
                axial = demand_p / float(max(curves["x"][0].max(), 1e-9))
            else:
                axial = -demand_p / float(max(-curves["x"][0].min(), 1e-9))
            u = max(axial, sum(parts))
            if worst_i is None or u > worst_i[0]:
                worst_i = (u, st.combination, st.where[k], b1)
    clause_c = cite(table, f"{key}Compression")
    if worst_c is not None:
        checks.append(
            _row(
                "compression (flexural buckling)",
                worst_c[1],
                phi_c * pn,
                "kN",
                clause_c,
                f"Po = {po / 1e3:.0f} kN, Pe = {pe_min / 1e3:.0f} kN (KLx {kl['x']:.0f}, KLy "
                f"{kl['y']:.0f} mm), C = {sec.c_stiff:.2f}",
                worst_c[2],
                scale=1e3,
            )
        )
    if worst_t is not None:
        checks.append(
            _row(
                "tension (yielding)",
                worst_t[1],
                phi_t * pnt,
                "kN",
                cite(table, f"{key}Tension"),
                combination=worst_t[2],
                scale=1e3,
            )
        )
    if worst_i is not None:
        u, combination, where, b1 = worst_i
        checks.append(
            {
                **_row(
                    "axial force and flexure (plastic P-M)",
                    u,
                    1.0,
                    "",
                    cite(table, "interaction"),
                    f"at {where}; Pn/Po = {lam:.2f} on the axial strength; B1 x {b1['x']:.2f}, "
                    f"y {b1['y']:.2f}; Mux/φMcx + Muy/φMcy at the axial force",
                    combination,
                ),
            }
        )
    checks += _column_scope(shape, sec, steel, fy, concrete, col, stations, table, cl)
    checks += _column_transfer(sec, fy, po, col, concrete, stations, seismic, table)
    summary = {
        "form": col.form,
        "Po": round(po / 1e3, 0),
        "Pn": round(pn / 1e3, 0),
        "phiPn": round(phi_c * pn / 1e3, 0),
        "EIeffX": round(effective_stiffness(sec, concrete.ec, es, "x") / 1e9, 1),
        "EIeffY": round(effective_stiffness(sec, concrete.ec, es, "y") / 1e9, 1),
        "steelShare": round(sec.as_ / sec.ag, 4),
        "barRatio": round(sec.asr / sec.ag, 4),
    }
    return {"checks": checks, "summary": summary, "notes": notes}


def _column_scope(
    shape: Any,
    sec: ColumnSection,
    steel: Any,
    fy: float,
    concrete: Concrete,
    col: Any,
    stations: list[Any],
    table: Any,
    cl: Any,
) -> list[dict[str, Any]]:
    rules = table.column
    rows = [
        _row(
            "steel share of the section",
            sec.as_ / sec.ag,
            rules.steelShareMin,
            "",
            cite(table, "encasedScope" if col.form == "encased" else "filledScope"),
            upper=False,
        )
    ]
    if col.form == "encased":
        e = rules.encased
        klass = cl.section_class(cl.compression_elements(shape, fy, steel.e))
        rows.append(
            _row(
                "steel shape compact or noncompact",
                2.0 if klass == cl.SLENDER else 0.0,
                1.0,
                "",
                cite(table, "encasedScope"),
                f"the shape is {klass}",
            )
        )
        if concrete.fc_given < table.materials.concreteMin:
            rows.append(
                _row(
                    "concrete f'c",
                    concrete.fc_given,
                    table.materials.concreteMin,
                    "MPa",
                    cite(table, "materials"),
                    upper=False,
                )
            )
        clause_b = cite(table, "encasedBars")
        rows.append(
            _row(
                "bar ratio ρsr (scope)",
                sec.asr / sec.ag,
                e.barRatioMin,
                "",
                cite(table, "encasedScope"),
                upper=False,
            )
        )
        rows.append(
            _row(
                "bar area / Ag (detailing)",
                sec.asr / sec.ag,
                e.barRatioDetailing,
                "",
                clause_b,
                upper=False,
            )
        )
        rows.append(
            _row("bar area / net concrete", sec.asr / max(sec.ac, 1.0), e.barRatioMax, "", clause_b)
        )
        rows.append(
            _row("bars at the corners", float(min(col.bars, 4)), 4.0, "bars", clause_b, upper=False)
        )
        spacing = _largest_bar_gap(sec.bars)
        if spacing:
            rows.append(
                _row(
                    "bar spacing",
                    spacing,
                    e.barSpacingLeastShare * sec.least,
                    "mm",
                    clause_b,
                    f"at most {e.barSpacingLeastShare:g} × the least side",
                )
            )
        rows.append(_row("clear cover", col.cover, e.cover, "mm", clause_b, upper=False))
        clause_t = cite(table, "encasedTies")
        tie_need = max(e.tieGreatestSideShare * sec.greatest, e.tieSmall)
        if sec.greatest > e.tieSmallSideMax:
            tie_need = max(tie_need, e.tieLarge)
        tie_need = min(tie_need, e.tieRequiredMax)
        rows.append(_row("tie diameter", col.tieDiameter, tie_need, "mm", clause_t, upper=False))
        tie_max = min(
            e.tieSpacingLeastShare * sec.least,
            e.tieSpacingBarDiameters * col.barDiameter,
            e.tieSpacingMax,
            e.tieSpacingTieDiameters * col.tieDiameter,
            e.tieSpacingLeastHalf * sec.least,
        )
        rows.append(_row("tie spacing", col.tieSpacing, tie_max, "mm", clause_t))
        tie_area = 2 * math.pi * col.tieDiameter**2 / 4 / col.tieSpacing
        rows.append(
            _row(
                "tie area per tie spacing",
                tie_area,
                e.tieAreaPerSpacing,
                "mm²/mm",
                cite(table, "encasedScope"),
                "as printed; advisory until the value is confirmed (two tie legs counted)",
                flag=True,
                upper=False,
            )
        )
        if fy > e.coreFyMaxTied:
            rows.append(
                _row(
                    "core Fy (reinforced concrete method)",
                    fy,
                    e.coreFyMaxTied,
                    "MPa",
                    cite(table, "coreFyMaxTied"),
                    "a limit of the reinforced concrete method; the composite chapter's "
                    "strength is used",
                    flag=True,
                )
            )
    else:
        f = rules.filled
        d = shape.dims
        clause = cite(table, "filledScope")
        bending = any(np.max(np.abs(st.Mx)) > 0 or np.max(np.abs(st.My)) > 0 for st in stations)
        lo = f.concreteBendingMin if bending else f.concreteAxialMin
        hi = f.concreteBendingMax if bending else f.concreteAxialMax
        rows.append(_row("concrete f'c (least)", concrete.fc_given, lo, "MPa", clause, upper=False))
        rows.append(
            _row(
                "concrete f'c (largest)",
                concrete.fc_given,
                hi,
                "MPa",
                clause,
                "with bending" if bending else "axially loaded",
            )
        )
        wall_clause = cite(table, "filledWall")
        if shape.family == "rhs":
            ratio = max(d["b"], d["h"]) / d["t"]
            rows.append(_row("wall b/t", ratio, f.rectSlenderness / math.sqrt(fy), "", clause))
            need = max(d["B"], d["H"]) * math.sqrt(steel.fy / (f.wallRectangular * steel.e))
        else:
            ratio = d["D"] / d["t"]
            rows.append(_row("wall D/t", ratio, f.roundSlenderness / fy, "", clause))
            need = d["D"] * math.sqrt(steel.fy / (f.wallCircular * steel.e))
        rows.append(_row("wall thickness", d["t"], need, "mm", wall_clause, upper=False))
    return rows


def _largest_bar_gap(bars: list[tuple[float, float]]) -> float:
    """The largest distance between neighbouring bars around the perimeter [mm]."""
    if len(bars) < 2:
        return 0.0
    angles = sorted(bars, key=lambda p: math.atan2(p[1], p[0]))
    gaps = [math.dist(angles[i], angles[(i + 1) % len(angles)]) for i in range(len(angles))]
    return max(gaps)


def _column_transfer(
    sec: ColumnSection,
    fy: float,
    po: float,
    col: Any,
    concrete: Concrete,
    stations: list[Any],
    seismic: bool,
    table: Any,
) -> list[dict[str, Any]]:
    """The force transfer between steel and concrete: the share that crosses by studs (or the
    bearing on the concrete), for the column's largest compression."""
    if col.transferForce is not None:
        v = col.transferForce * 1e3
        assumption = "the force introduced as given"
    else:
        v = max((float(np.max(st.P)) for st in stations), default=0.0)
        assumption = "the column's largest compression taken as the force introduced"
    if v <= 0:
        return []
    rows = []
    key = "encased" if col.form == "encased" else "filled"
    clause = cite(table, f"{key}Transfer")
    steel_share = sec.as_ * fy / po
    if col.form == "filled":
        assumption += "; the shares of the encased column used"
    rules = table.column
    if col.loadApplied == "bearing":
        if col.bearingArea is None:
            raise CompositeError("give the loaded concrete area for the bearing transfer")
        cap = table.phi.bearing * rules.bearingCoefficient * concrete.fc * col.bearingArea
        return_note = assumption
        if seismic:
            cap *= 1 - table.connections.seismicReduction
            return_note += (
                f"; reduced by {table.connections.seismicReduction:.0%} in the seismic system "
                f"({cite(table, 'seismicReduction')})"
            )
        return [
            _row(
                "bearing on the concrete",
                v,
                cap,
                "kN",
                clause,
                return_note,
                scale=1e3,
            )
        ]
    v_prime = v * (1 - steel_share) if col.loadApplied == "steel" else v * steel_share
    qn = stud_strength(col.studDiameter, col.studFu, concrete, table)
    depth = sec.greatest
    length = (
        2 * rules.encased.connectorLength * depth
        if col.form == "encased"
        else (2 * rules.filled.connectorLength * depth)
    )
    count = col.studFaces * max(1, math.floor(length / col.studSpacing))
    rows.append(
        _row(
            "load transfer studs",
            v_prime,
            count * qn,
            "kN",
            f"{clause}; {cite(table, f'{key}Stud' if col.form == 'encased' else 'encasedStud')}",
            f"{count} studs Ø{col.studDiameter:g} over {length:.0f} mm, Qn = {qn / 1e3:.0f} kN "
            f"(nominal, the code gives no φ); {assumption}; bond ignored "
            f"({cite(table, 'connections')})",
            scale=1e3,
        )
    )
    rows.append(
        _row(
            "load transfer stud spacing",
            col.studSpacing,
            rules.connectorSpacingMax,
            "mm",
            cite(table, f"{key}Connectors"),
        )
    )
    if col.form == "encased":
        rows.append(
            _row(
                "faces with transfer studs",
                col.studFaces,
                2,
                "faces",
                cite(table, "encasedConnectors"),
                "symmetric about the shape's axes",
                upper=False,
            )
        )
    return rows


# ─────────────────────────────────────── connections ───────────────────────────────────────


def connection_rows(object_type: Any, table: Any) -> list[dict[str, Any]]:
    """The composite connection rules a member's type triggers (advisories)."""
    rows = []
    composite = getattr(object_type, "composite", None)
    if getattr(composite, "embeddedEnds", False):
        rows.append(
            _row(
                "face bearing plates",
                1.0,
                1.0,
                "",
                cite(table, "faceBearingPlates"),
                "stiffeners between the flanges are required where the beam is embedded in a "
                "reinforced concrete column or wall; the connection region needs hoops "
                f"({cite(table, 'connections')})",
                flag=True,
            )
        )
    if getattr(composite, "form", None) == "encased":
        rows.append(
            _row(
                "panel zone (encased)",
                1.0,
                1.0,
                "",
                cite(table, "panelZone"),
                "the panel zone's shear strength is the steel's plus the confined reinforced "
                "concrete's; transfer forces by studs, bearing or shear friction, bond ignored",
                flag=True,
            )
        )
    return rows


# ───────────────────────────────────────── the member ─────────────────────────────────────────

#: The steel-alone checks a composite column replaces (kept as advisories).
_COLUMN_REPLACED = (
    "Compression: buckling",
    "Flexure about x (major)",
    "Flexure about y (minor)",
    "Axial force and flexure (H1)",
    "Tension: yielding (gross section)",
)


def apply(
    entry: dict[str, Any],
    kind: str,
    object_type: Any,
    material: Any,
    mats: dict[str, Any],
    stations: list[Any],
    lengths: Any,
    combinations: list[str],
    table: Any = None,
) -> None:
    """Add the composite checks of a steel beam or column whose type sets ``composite`` to its
    design report ``entry`` (in place): ``"Composite: ..."`` rows, ``entry["composite"]`` (the
    summary and, for beams, the deflection data), notes; the steel-alone rows the composite
    section replaces become advisories. Nothing when the type is not composite. A note instead
    when the pack has no composite rules or the inputs cannot be checked."""
    composite = getattr(object_type, "composite", None)
    if composite is None:
        return
    notes = entry["section"].setdefault("notes", [])
    table = table if table is not None else composite_table()
    if table is None:
        notes.append("composite action not checked: the code pack does not cover it")
        return
    from saengine.design.steel.properties import shape_properties

    try:
        shape = shape_properties(object_type.profile)
        concrete_material = mats.get(composite.concrete)
        if concrete_material is None:
            raise CompositeError(f"no material '{composite.concrete}' for the concrete")
        if kind == "beam" and composite.type == "compositeBeam":
            flexure = next(
                (c for c in entry["checks"] if c["name"] == "Flexure about x (major)"), None
            )
            found = beam_checks(
                shape,
                material,
                concrete_material,
                composite,
                stations,
                lengths.length,
                flexure,
                table,
            )
            if flexure is not None:
                _advisory(flexure, "the composite section's flexure checks replace it")
        elif kind == "column" and composite.type == "compositeColumn":
            found = column_checks(
                shape,
                material,
                concrete_material,
                composite,
                stations,
                lengths,
                _seismic(object_type, combinations),
                table,
            )
            for c in entry["checks"]:
                if c["name"] in _COLUMN_REPLACED:
                    _advisory(c, "the composite column's checks replace it")
        else:
            raise CompositeError(f"a {composite.type} does not apply to a {kind}")
    except (CompositeError, KeyError, ZeroDivisionError) as error:
        notes.append(f"composite action not checked: {error}")
        return
    found["checks"] += connection_rows(object_type, table)
    entry["checks"] += found["checks"]
    entry["composite"] = {"type": composite.type, **found["summary"]}
    if "deflection" in found:
        entry["composite"]["deflection"] = found["deflection"]
    notes.extend(f"composite: {n}" for n in found["notes"])
    notes.append(_describe(entry["composite"]))
    strength = [c for c in entry["checks"] if not c["flag"]]
    entry["utilisation"] = max((c["utilisation"] for c in strength), default=0.0)
    entry["ok"] = all(c["ok"] for c in strength)


def _advisory(check: dict[str, Any], why: str) -> None:
    check["flag"] = True
    check["note"] = f"{check['note']}; {why}" if check.get("note") else why


def _seismic(object_type: Any, combinations: list[str]) -> bool:
    """Whether the column belongs to the seismic system: not a gravity-only member, and the
    run has earthquake combinations."""
    import re

    if getattr(object_type, "seismicRole", "auto") == "gravity":
        return False
    return any("E" in re.findall(r"[A-Za-z]+", c) for c in combinations)


def _describe(summary: dict[str, Any]) -> str:
    if summary.get("type") == "compositeBeam":
        connector = "studs" if summary["connector"] == "stud" else "channels"
        how = "designed" if summary["designedSpacing"] else "given"
        return (
            f"composite beam: beff {summary['effectiveWidth']:.0f} mm; {summary['connectors']} "
            f"{connector} ({summary['perRow']} per row @ {summary['spacing']:.0f} mm, {how}), "
            f"Qn {summary['qn']:g} kN (Rg {summary['rg']:g}, Rp {summary['rp']:g}); "
            f"{summary['ratio']:.0%} composite; Ie {summary['Ie']:g}e6 mm⁴"
        )
    return (
        f"composite column ({summary['form']}): Po {summary['Po']:.0f} kN, φPn "
        f"{summary['phiPn']:.0f} kN; EIeff {summary['EIeffX']:g} / {summary['EIeffY']:g} kN·m²"
    )


__all__ = [
    "METHOD",
    "CompositeError",
    "adjust_deflection_rows",
    "apply",
    "beam_checks",
    "column_checks",
    "composite_table",
    "concrete_modulus",
    "effective_width",
    "plastic_positive",
    "scale_profiles",
    "stud_factors",
    "stud_strength",
]

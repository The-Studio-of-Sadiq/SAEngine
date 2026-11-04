"""Composite slabs on profiled steel deck (alpha 9 P8), under the code pack's ``compositeSlab``
table (:class:`saengine.codes.composite_slab_tables.CompositeSlabTable`); a pack without it
does not check composite slabs (the slab is then designed as a concrete slab only).

The slab spans one way along the deck's ribs (the slab type's ``compositeDeck``), per metre
width, simply supported over ``span`` (the slab's extent along the ribs when not given):

**The deck** (per metre): Ap, its centroid e and plastic neutral axis ep above its bottom, Ip
and the plastic moment Mpa at fyp,d = fyp / γap, from the trapezoidal geometry (two flanges and
two inclined webs of the core thickness, embossments and the effective widths of the thin
plates left out), or the manufacturer's values where the type gives them.

**Construction stage** (the deck alone, unpropped): the wet concrete (its density +
``wetIncrement``) and the deck, and the construction load: ``workingShare`` × the concrete's
weight within ``workingMin``-``workingMax`` over a working length at mid-span, ``outside``
elsewhere; MEd = γG g L²/8 + γQ (q_out L²/8 + (q_in - q_out) a (2L - a)/8) of one span, the
moments of equal continuous spans fully loaded (0.125 w L² over the support, 0.070 g L² + 0.096
q L² in the span) otherwise; the deflection under the deck and the wet concrete, 5/384 (one
span) or 1/185 (continuous) w L⁴ / (E Ip), against L / ``deflection.construction``; ponding:
above ``ponding.threshold`` × h the concrete is deeper by ``ponding.share`` × δ.

**Composite stage**:

- sagging bending by the plastic stress distribution with full connection: Np = Ap fyp,d,
  Ncf = ``concreteShare`` fcd b hc; Np <= Ncf: MRd = Np (dp - x/2), x = Np / (``concreteShare``
  fcd b); else Mpr = ``plasticReduction`` Mpa (1 - Ncf / Np) <= Mpa, z = h - hc/2 - ep + (ep - e)
  Ncf / Np, MRd = Ncf z + Mpr;
- longitudinal shear, by the pack's methods the deck's tests allow: ``mk`` V_l,Rd = b dp / γVs
  (m Ap / (b Ls) + k) with Ls = ``shearSpanShare`` L, against the support shear; or
  ``partialConnection``: Nc = τu,Rk / γVs b x <= Ncf at every x from the support, MRd(x) = Nc
  z + Mpr with Nc in place of Ncf, against MEd(x);
- vertical shear: VRd,c of the pack's ``concreteMethods.shear`` (:func:`saengine.design.
  strut_shear.concrete_resistance`) on the ribs' mean width per metre and dp;
- deflection in service: the deck's construction deflection (unpropped) + the composite slab's
  under the loads after it hardens (all of them when propped), 5 w L⁴ / (384 Ea I), I the mean
  of the cracked and uncracked sections with n = ``modularFactor`` Ea / Ecm, against L /
  ``deflection.service``;
- the least depths overall and above the ribs; the anti-crack bars above the ribs (``antiCrack``
  × the concrete above them, unpropped or propped) and ``meshMinimum`` each way.

The slab's own concrete checks (bars, moments of the analysis or the coefficient methods) are
kept as advisories: the composite slab's replace them. Units: N, mm, MPa (kN/m² = N/mm per
metre width).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

#: Generic trapezoidal profiles (geometry only, not a product's: check against the deck used).
DECK_PROFILES: dict[str, dict[str, float]] = {
    "generic trapezoidal 46/150": {
        "ribHeight": 46,
        "pitch": 150,
        "ribTopWidth": 100,
        "ribBottomWidth": 60,
    },
    "generic trapezoidal 60/300": {
        "ribHeight": 60,
        "pitch": 300,
        "ribTopWidth": 180,
        "ribBottomWidth": 120,
    },
    "generic trapezoidal 80/300": {
        "ribHeight": 80,
        "pitch": 300,
        "ribTopWidth": 190,
        "ribBottomWidth": 120,
    },
}

STEEL_WEIGHT = 77.0  # kN/m³ of the deck's steel (7850 kg/m³)
WIDTH = 1000.0  # mm: per metre width

METHOD = [
    (
        "Composite slabs on profiled steel deck (the slab type's composite deck), under the code "
        "pack's compositeSlab table: one way along the ribs, simply supported, per metre; the "
        "deck alone under the wet concrete and the construction load (bending, deflection, "
        "ponding); the composite slab's plastic sagging resistance, its longitudinal shear by "
        "the m-k or the partial connection method from the deck's tests, the vertical shear, "
        "the deflection on the mean of the cracked and uncracked sections, the least depths and "
        "the anti-crack bars. Listed as 'Composite slab: ...' checks; the slab's concrete checks "
        "are kept as advisories."
    )
]


class CompositeSlabError(ValueError):
    """The composite slab cannot be checked (inputs outside what the method covers)."""


def table() -> Any | None:
    """The ``compositeSlab`` table of the pack in force; None when it does not cover it."""
    from saengine.codes import context as code_context

    pack = code_context.current()
    return pack.table("compositeSlab") if pack.has("compositeSlab") else None


def _cite(rules: Any, key: str) -> str:
    return str(rules.sources.get(key, "")).split(" (", 1)[0]


def _row(
    name: str,
    demand: float,
    capacity: float,
    unit: str,
    clause: str,
    note: str = "",
    combination: str | None = None,
    flag: bool = False,
    upper: bool = True,
) -> dict[str, Any]:
    """A design check row (``upper``: demand <= capacity, else demand >= capacity)."""
    if upper:
        u = demand / capacity if capacity > 0 else (0.0 if demand <= 0 else 99.0)
    else:
        u = capacity / demand if demand > 0 else (0.0 if capacity <= 0 else 99.0)
    u = round(float(u), 3) if math.isfinite(u) else 99.0
    return {
        "name": f"Composite slab: {name}",
        "demand": round(float(demand), 2),
        "capacity": round(float(capacity), 2),
        "unit": unit,
        "utilisation": u,
        "combination": combination,
        "ok": bool(u <= 1.0),
        "note": note,
        "flag": flag,
        "clause": clause,
    }


# ─────────────────────────────────────── the deck ───────────────────────────────────────


@dataclass(frozen=True)
class DeckSection:
    """The deck per metre width: Ap [mm²/m], e and ep above its bottom [mm], Ip [mm⁴/m], Mpa
    [N·mm/m] at fyp,d, its weight [kN/m²] and the concrete ribs (mean width b0, pitch, hp)."""

    hp: float
    pitch: float
    b0: float
    ap: float
    e: float
    ep: float
    ip: float
    mpa: float
    weight: float
    notes: tuple[str, ...] = ()

    @property
    def ribs_share(self) -> float:
        """The concrete ribs' share of the plan (b0 / pitch)."""
        return min(1.0, self.b0 / self.pitch)


def geometry(deck: Any) -> dict[str, float]:
    """The deck's (hp, pitch, rib widths): the generic profile's when the type names one."""
    if deck.profile:
        found = DECK_PROFILES.get(deck.profile)
        if found is None:
            raise CompositeSlabError(f"unknown deck profile '{deck.profile}'")
        return dict(found)
    return {
        "ribHeight": float(deck.ribHeight),
        "pitch": float(deck.pitch),
        "ribTopWidth": float(deck.ribTopWidth),
        "ribBottomWidth": float(deck.ribBottomWidth),
    }


def deck_section(deck: Any, fypd: float) -> DeckSection:
    """:class:`DeckSection` of the type's ``compositeDeck`` at the design strength ``fypd``."""
    g = geometry(deck)
    hp, pitch = g["ribHeight"], g["pitch"]
    top, bottom = g["ribTopWidth"], g["ribBottomWidth"]
    if top >= pitch or bottom >= pitch:
        raise CompositeSlabError("the ribs are wider than their pitch")
    t = float(deck.thickness)
    crest = pitch - top  # the deck's top flange between the concrete ribs
    web = math.hypot(hp, (top - bottom) / 2)
    a_bottom, a_top, a_web = t * bottom, t * crest, t * web  # per pitch, one web
    area = a_bottom + a_top + 2 * a_web
    e = (a_top * hp + 2 * a_web * hp / 2) / area
    ip = (
        a_bottom * e**2
        + a_top * (hp - e) ** 2
        + 2 * (a_web * hp**2 / 12 + a_web * (hp / 2 - e) ** 2)
    )
    # The plastic neutral axis: half the area below it (the webs linear in height).
    half = area / 2
    if half <= a_bottom:
        ep = 0.0
    elif half >= a_bottom + 2 * a_web:
        ep = hp
    else:
        ep = (half - a_bottom) * hp / (2 * a_web)
    first = a_bottom * ep + a_top * (hp - ep) + 2 * a_web / hp * (ep**2 + (hp - ep) ** 2) / 2
    per_metre = WIDTH / pitch
    notes = []
    ap = area * per_metre
    if deck.area is not None:
        ap = float(deck.area)
        notes.append("Ap as given")
    if deck.centroid is not None:
        e = float(deck.centroid)
        notes.append("e as given")
    mpa = fypd * first * per_metre
    if deck.plasticMoment is not None:
        mpa = float(deck.plasticMoment) * 1e6
        notes.append("Mpa as given")
    ip_m = ip * per_metre
    if deck.inertia is not None:
        ip_m = float(deck.inertia)
        notes.append("Ip as given (effective)")
    else:
        notes.append("Ip of the gross section (no effective widths, embossments left out)")
    weight = (
        float(deck.weight)
        if deck.weight is not None
        else STEEL_WEIGHT * area * per_metre / 1e6  # kN/m² of the steel per plan area
    )
    return DeckSection(hp, pitch, (top + bottom) / 2, ap, e, ep, ip_m, mpa, weight, tuple(notes))


# ─────────────────────────────────────── the slab ───────────────────────────────────────


@dataclass
class SlabInputs:
    """One composite slab: ``h`` its overall depth [mm], the concrete (fck, Ecm [MPa], density
    [kN/m³]), ``span`` [mm], the loads after the concrete hardens [kN/m²]: ``superimposed``
    (finishes, partitions in the dead load) and ``live``; ``combinations``: (name, dead factor,
    live factor) of the strength combinations; ``top``: the bars above the ribs each way
    [mm²/m] (x, y; None where there are none)."""

    h: float
    fck: float
    ecm: float
    density: float
    span: float
    superimposed: float
    live: float
    combinations: list[tuple[str, float, float]]
    top: tuple[float | None, float | None] = (None, None)
    notes: list[str] = field(default_factory=list)


def _construction_moments(
    span: float, g: float, q_in: float, q_out: float, a: float, spans: int, rules: Any
) -> tuple[float, float]:
    """(sagging, hogging) design moments [N·mm/m] of the deck under the wet concrete ``g``
    [N/mm per m] and the construction load (``q_in`` over ``a`` [mm], ``q_out`` elsewhere)."""
    gg, gq = float(rules.gammaG), float(rules.gammaQ)
    if spans <= 1:
        patch = (q_in - q_out) * a * (2 * span - a) / 8
        return gg * g * span**2 / 8 + gq * (q_out * span**2 / 8 + patch), 0.0
    q = q_in  # the working area anywhere: on the safe side over the whole span
    sag = 0.070 * gg * g * span**2 + 0.096 * gq * q * span**2
    hog = 0.125 * (gg * g + gq * q) * span**2
    return sag, hog


def construction_rows(
    deck: Any, sec: DeckSection, inp: SlabInputs, rules: Any, fypd: float
) -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
    """The deck alone under the wet concrete: rows, its deflection [mm] (0 when propped) and
    the summary values."""
    if deck.propped:
        return [], 0.0, {"construction": "propped: the props carry the wet concrete"}
    span = inp.span
    mean = inp.h - sec.hp * (1 - sec.ribs_share)  # concrete per plan area [mm]
    wet = inp.density + float(rules.wetIncrement)  # kN/m³
    concrete = wet * mean / 1e3  # kN/m²
    c_defl = 5 / 384 if deck.spans <= 1 else 1 / 185
    e_ip = float(deck.E) * sec.ip

    def deflection(load: float) -> float:
        return c_defl * load * span**4 / e_ip

    delta = deflection(concrete + sec.weight)
    ponding = ""
    pond = rules.ponding
    if delta > float(pond.threshold) * inp.h:
        extra = wet * float(pond.share) * delta / 1e3
        concrete += extra
        delta = deflection(concrete + sec.weight)
        ponding = f"; ponding: + {extra:.2f} kN/m² ({_cite(rules, 'ponding')})"
    cl = rules.constructionLoad
    q_in = min(max(float(cl.workingShare) * concrete, float(cl.workingMin)), float(cl.workingMax))
    q_out = float(cl.outside)
    a = min(float(cl.workingLength), span)
    sag, hog = _construction_moments(span, concrete + sec.weight, q_in, q_out, a, deck.spans, rules)
    given = deck.momentResistance is not None
    if given:
        mrd = float(deck.momentResistance) * 1e6
        how = "the manufacturer's MRd"
    else:
        wel = sec.ip / max(sec.e, sec.hp - sec.e, 1e-9)
        mrd = wel * fypd
        how = (
            "the gross elastic section (the thin plates' effective section is smaller: give "
            "the manufacturer's MRd)"
        )
    note = (
        f"wet concrete {concrete:.2f} + deck {sec.weight:.2f} kN/m², construction load "
        f"{q_in:.2f} kN/m² over {a:.0f} mm, {q_out:.2f} elsewhere"
        f"{ponding}; {'one span' if deck.spans <= 1 else f'{deck.spans} continuous spans'}; "
        f"{how}"
    )
    clause = _cite(rules, "construction")
    rows = [
        _row(
            "deck bending, construction stage",
            sag / 1e6,
            mrd / 1e6,
            "kN·m/m",
            clause,
            note,
            flag=not given,
        )
    ]
    if deck.spans > 1:
        hog_rd = float(deck.hoggingResistance or deck.momentResistance or 0.0) * 1e6 or mrd
        rows.append(
            _row(
                "deck bending over the supports, construction stage",
                hog / 1e6,
                hog_rd / 1e6,
                "kN·m/m",
                clause,
                "equal spans fully loaded (0.125 w L²)",
                flag=not given,
            )
        )
    limit = span / float(rules.deflection.construction)
    rows.append(
        _row(
            "deck deflection, construction stage",
            delta,
            limit,
            "mm",
            _cite(rules, "constructionDeflection"),
            f"deck and wet concrete, L/{float(rules.deflection.construction):g}; "
            + "; ".join(sec.notes),
        )
    )
    return (
        rows,
        delta,
        {"wetLoad": round(concrete + sec.weight, 2), "deckDeflection": round(delta, 1)},
    )


def moment_resistance(
    nc: float, np_: float, sec: DeckSection, h: float, block: float, reduction: float
) -> float:
    """MRd [N·mm/m] with the slab's compression ``nc`` [N/m] (the full connection's least of Np
    and Ncf, or less), ``block`` the plastic stress of the concrete [MPa], ``reduction`` the
    table's ``plasticReduction`` of Mpr."""
    x = nc / (block * WIDTH)
    dp = h - sec.e
    if nc >= np_ * (1 - 1e-9):
        return np_ * (dp - x / 2)
    share = nc / np_
    mpr = min(reduction * sec.mpa * (1 - share), sec.mpa)
    z = h - 0.5 * x - sec.ep + (sec.ep - sec.e) * share
    return nc * z + mpr


def composite_rows(
    deck: Any, sec: DeckSection, inp: SlabInputs, rules: Any, fypd: float, delta_wet: float
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The composite slab's rows (see the module notes) and its summary values."""
    rows: list[dict[str, Any]] = []
    h, span = inp.h, inp.span
    hc = h - sec.hp
    if hc <= 0:
        raise CompositeSlabError("the slab is not deeper than the deck")
    th = rules.thickness
    clause_t = _cite(rules, "thickness")
    least_h = float(th.beamFlangeOverall if deck.beamFlange else th.overall)
    least_hc = float(th.beamFlangeAboveRibs if deck.beamFlange else th.aboveRibs)
    rows.append(_row("overall depth", h, least_h, "mm", clause_t, upper=False))
    rows.append(_row("depth above the ribs", hc, least_hc, "mm", clause_t, upper=False))

    # Loads [kN/m² = N/mm per metre]; the design load of each combination.
    mean = h - sec.hp * (1 - sec.ribs_share)
    own = inp.density * mean / 1e3 + sec.weight
    dead = own + inp.superimposed
    if not inp.combinations:
        raise CompositeSlabError("no gravity strength combination")
    name, f_d, f_l = max(inp.combinations, key=lambda c: c[1] * dead + c[2] * inp.live)
    w_ed = f_d * dead + f_l * inp.live
    m_ed = w_ed * span**2 / 8
    v_ed = w_ed * span / 2
    fcd = inp.fck / float(rules.gammaC)
    block = float(rules.concreteShare) * fcd
    np_ = sec.ap * fypd
    ncf = block * WIDTH * hc
    nc_full = min(np_, ncf)
    reduction = float(rules.plasticReduction)
    m_rd = moment_resistance(nc_full, np_, sec, h, block, reduction)
    where = "the slab" if np_ <= ncf else "the deck"
    rows.append(
        _row(
            "sagging bending (plastic)",
            m_ed / 1e6,
            m_rd / 1e6,
            "kN·m/m",
            _cite(rules, "bending"),
            f"wEd = {w_ed:.2f} kN/m², Np = {np_ / 1e3:.0f} kN/m, Ncf = {ncf / 1e3:.0f} kN/m: the "
            f"neutral axis in {where}; dp = {h - sec.e:.0f} mm",
            name,
        )
    )

    # Longitudinal shear by the methods the pack allows and the tests give.
    methods = list(rules.longitudinalShear)
    gv = float(rules.gammaVs)
    dp = h - sec.e
    if "mk" in methods and deck.m is not None and deck.k is not None:
        ls = float(rules.shearSpanShare) * span
        v_l = WIDTH * dp / gv * (float(deck.m) * sec.ap / (WIDTH * ls) + float(deck.k))
        rows.append(
            _row(
                "longitudinal shear (m-k)",
                v_ed / 1e3,
                v_l / 1e3,
                "kN/m",
                _cite(rules, "mk"),
                f"V_l,Rd = b dp / γVs (m Ap / (b Ls) + k), m = {deck.m:g}, k = {deck.k:g} N/mm², "
                f"Ls = {ls:.0f} mm",
                name,
            )
        )
    elif "partialConnection" in methods and deck.tauU is not None:
        tau = float(deck.tauU) / gv
        worst = (0.0, 0.0, 0.0, 0.0)
        for i in range(1, 21):
            x = span / 2 * i / 20
            m_x = w_ed * x * (span - x) / 2
            nc = min(tau * WIDTH * x, nc_full)
            r = moment_resistance(nc, np_, sec, h, block, reduction)
            u = m_x / r if r > 0 else math.inf
            if u > worst[0]:
                worst = (u, x, m_x, r)
        _, x, m_x, r = worst
        rows.append(
            _row(
                "longitudinal shear (partial connection)",
                m_x / 1e6,
                r / 1e6,
                "kN·m/m",
                _cite(rules, "partial"),
                f"at {x:.0f} mm from the support: Nc = τu,Rd b x <= Ncf, τu,Rd = "
                f"{deck.tauU:g} / {gv:g} N/mm²",
                name,
            )
        )
    else:
        wanted = " or ".join({"mk": "m and k", "partialConnection": "τu,Rk"}[m] for m in methods)
        rows.append(
            _row(
                "longitudinal shear",
                v_ed / 1e3,
                0.0,
                "kN/m",
                _cite(rules, "mk" if "mk" in methods else "partial"),
                f"not checked: give the deck's test values ({wanted}) from the manufacturer",
                name,
                flag=True,
            )
        )

    # Vertical shear by the pack's concrete shear method.
    from saengine.design import strut_shear

    shear_rules = strut_shear.rules()
    bw = WIDTH * sec.ribs_share
    if shear_rules is not None:
        rho = sec.ap / (bw * dp)
        v_rd = strut_shear.concrete_resistance(bw, dp, rho, inp.fck, 0.0, shear_rules)
        rows.append(
            _row(
                "vertical shear",
                v_ed / 1e3,
                v_rd / 1e3,
                "kN/m",
                _cite(rules, "verticalShear"),
                f"VRd,c on bw = {bw:.0f} mm/m, dp = {dp:.0f} mm, ρl = Ap / (bw dp) = {rho:.4f}",
                name,
            )
        )
    else:
        inp.notes.append("vertical shear not checked: the code pack has no concrete shear method")

    # Deflection in service on the mean of the cracked and uncracked sections.
    ea = float(deck.E)
    n = float(rules.modularFactor) * ea / inp.ecm
    i_mean = (uncracked_inertia(sec, h, n) + cracked_inertia(sec, h, n)) / 2
    after = inp.superimposed + inp.live + (own if deck.propped else 0.0)
    delta_c = 5 * after * span**4 / (384 * ea * i_mean)
    total = delta_wet + delta_c
    limit = span / float(rules.deflection.service)
    rows.append(
        _row(
            "deflection in service",
            total,
            limit,
            "mm",
            _cite(rules, "deflection"),
            f"{'' if deck.propped else f'deck {delta_wet:.1f} mm + '}composite {delta_c:.1f} mm "
            f"under {after:.2f} kN/m² (n = {n:.1f}, I = {i_mean / 1e6:.1f}e6 mm⁴/m, the mean of "
            f"cracked and uncracked); L/{float(rules.deflection.service):g}",
        )
    )

    # Bars above the ribs.
    share = float(rules.antiCrack[1] if deck.propped else rules.antiCrack[0])
    need = share * hc * WIDTH
    given = [a for a in inp.top if a is not None]
    provided = min(given) if len(given) == 2 else 0.0
    clause_r = _cite(rules, "antiCrack")
    rows.append(
        _row(
            "anti-crack bars above the ribs",
            need,
            provided,
            "mm²/m",
            clause_r,
            f"{share:.1%} of the concrete above the ribs ("
            + ("propped" if deck.propped else "unpropped")
            + ")"
            + ("" if len(given) == 2 else "; give top bars both ways"),
        )
    )
    rows.append(
        _row(
            "bars above the ribs each way",
            float(rules.meshMinimum),
            provided,
            "mm²/m",
            _cite(rules, "mesh"),
        )
    )
    summary = {
        "span": round(span, 0),
        "wEd": round(w_ed, 2),
        "MRd": round(m_rd / 1e6, 2),
        "Ap": round(sec.ap, 0),
        "deckWeight": round(sec.weight, 3),
        "meanThickness": round(mean, 1),
    }
    return rows, summary


def _concrete_layers(sec: DeckSection, h: float) -> list[tuple[float, float, float]]:
    """(top, bottom, width) of the concrete per metre, from the top of the slab [mm]."""
    hc = h - sec.hp
    return [(0.0, hc, WIDTH), (hc, h, WIDTH * sec.ribs_share)]


def uncracked_inertia(sec: DeckSection, h: float, n: float) -> float:
    """I [mm⁴/m, steel units] of the uncracked section, the concrete / n."""
    from saengine.design.steel.composite import _Layers

    conc = _Layers(_concrete_layers(sec, h))
    dp = h - sec.e
    area = conc.area() / n + sec.ap
    y = (conc.moment() / n + sec.ap * dp) / area
    return conc.inertia(y) / n + sec.ip + sec.ap * (dp - y) ** 2


def cracked_inertia(sec: DeckSection, h: float, n: float) -> float:
    """I [mm⁴/m, steel units] of the cracked section: the concrete above the neutral axis."""
    from saengine.design.steel.composite import _Layers

    conc = _Layers(_concrete_layers(sec, h))
    dp = h - sec.e
    y = h / 2
    for _ in range(60):
        a_c = conc.area(y) / n
        y_new = (conc.moment(y) / n + sec.ap * dp) / (a_c + sec.ap)
        if abs(y_new - y) < 1e-6:
            break
        y = y_new
    return conc.inertia(y, y) / n + sec.ip + sec.ap * (dp - y) ** 2


def check(deck: Any, inp: SlabInputs, rules: Any | None = None) -> dict[str, Any]:
    """The composite slab's ``{"checks", "summary", "notes"}`` (see the module notes)."""
    rules = rules if rules is not None else table()
    if rules is None:
        raise CompositeSlabError("the code pack does not cover composite slabs")
    fypd = float(deck.fyp) / float(rules.gammaAp)
    sec = deck_section(deck, fypd)
    rows, delta, summary = construction_rows(deck, sec, inp, rules, fypd)
    more, found = composite_rows(deck, sec, inp, rules, fypd, delta)
    summary.update(found)
    summary["deck"] = deck.profile or (
        f"{sec.hp:g}/{sec.pitch:g} deck, t = {float(deck.thickness):g} mm, fyp {deck.fyp:g} MPa"
    )
    return {"checks": rows + more, "summary": summary, "notes": list(inp.notes)}


def apply(entry: dict[str, Any], deck: Any, inp: SlabInputs, notes: list[str]) -> None:
    """Add the composite slab's checks to a slab's design report ``entry`` (in place): the
    concrete slab's strength rows become advisories, ``entry["compositeSlab"]`` the summary. A
    note instead when the pack does not cover composite slabs or the inputs cannot be checked."""
    rules = table()
    if rules is None:
        notes.append(f"{entry['id']}: composite deck not checked: the code pack does not cover it")
        return
    try:
        found = check(deck, inp, rules)
    except (CompositeSlabError, ZeroDivisionError) as error:
        notes.append(f"{entry['id']}: composite deck not checked: {error}")
        return
    for c in entry["checks"]:
        if not c.get("flag"):
            c["flag"] = True
            why = "the composite slab's checks replace it"
            c["note"] = f"{c['note']}; {why}" if c.get("note") else why
    entry["checks"] = [*entry["checks"], *found["checks"]]
    entry["compositeSlab"] = found["summary"]
    strength = [c for c in entry["checks"] if not c["flag"]]
    entry["utilisation"] = max((c["utilisation"] for c in strength), default=0.0)
    entry["ok"] = all(c["ok"] for c in strength)
    notes.extend(f"{entry['id']}: composite deck: {n}" for n in found["notes"])


__all__ = [
    "DECK_PROFILES",
    "METHOD",
    "CompositeSlabError",
    "DeckSection",
    "SlabInputs",
    "apply",
    "check",
    "composite_rows",
    "construction_rows",
    "cracked_inertia",
    "deck_section",
    "moment_resistance",
    "table",
    "uncracked_inertia",
]

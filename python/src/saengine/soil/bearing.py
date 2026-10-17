"""Allowable bearing pressure of a spread footing at a borehole.

Net allowable pressure ``qa`` [kPa], compared with the net soil pressure under the service
loads (gross pressure minus the total overburden at the founding level, as
:mod:`saengine.design.footing` computes it). It is the lower of:

(a) Shear failure: the general bearing capacity equation with Vesic's (1973, 1975) factors,
    De Beer's shape factors and Hansen's (1970) depth factors, as tabulated by Vesic (1975) in
    Winterkorn & Fang, Foundation Engineering Handbook, ch. 3 (also in Bowles 1996, Foundation
    Analysis and Design, ch. 4, and Das, Principles of Foundation Engineering):

    ``qu = c Nc sc dc + q Nq sq dq + ½ γ B Nγ sγ dγ``

    - ``Nq = e^(π tanφ) tan²(45° + φ/2)``, ``Nc = (Nq - 1) cotφ`` (5.14 for φ = 0),
      ``Nγ = 2 (Nq + 1) tanφ``;
    - ``sc = 1 + (B/L)(Nq/Nc)``, ``sq = 1 + (B/L) tanφ``, ``sγ = 1 - 0.4 B/L ≥ 0.6``;
    - ``k = Df/B`` for Df ≤ B, else ``arctan(Df/B)`` [rad]: ``dc = 1 + 0.4 k``,
      ``dq = 1 + 2 tanφ (1 - sinφ)² k``, ``dγ = 1``;
    - vertical, centric load on level ground (no inclination, base or ground factors);
    - q = σ'v at the founding level; γ in the Nγ term: γ' below the water table, γ when the
      water table is deeper than B below the base, linear in between (the usual
      correction, e.g. Das, Principles of Foundation Engineering, ch. 4).

    Undrained clay (φ = 0, cu): ``qu - q = cu Nc sc dc`` with Nc = 5.14, sc = 1 + 0.2 B/L
    (Skempton-type short-term check, which governs footings on saturated clay). Cohesive layers
    with drained c', φ' are also checked drained and the lower value used. Each layer within B
    below the base is checked with its own parameters as if the footing stood on it, and the
    weakest governs (a conservative stand-in for a two-layer analysis). A layer within B below
    the base with no strength at all (no cu, φ' or SPT to estimate them) withholds qa: an
    unknown layer under the footing cannot be passed over. Then ``qa_shear = (qu - σ'v) / FS``:
    qu is computed with the effective overburden q = σ'v, so the gross total capacity is
    ``qu + u`` (u the pore pressure at the base) and the capacity net of the total overburden
    σv is ``qu + u - σv = qu - σ'v``, the same for the drained and the undrained case.

(b) Settlement, for granular soil: Meyerhof (1965) as modified by Bowles (1977), the SI form
    with N60 (Das, Principles of Foundation Engineering, eq. for the net allowable pressure for
    a settlement Se; Bowles 1996 gives the same form with N55 and F1 = 0.05, F2 = 0.08, F3 = 0.3 m, F4 = 1.2 m):

    - ``qa = 19.16 N60 Kd (Se/25)`` for B ≤ 1.22 m,
    - ``qa = 11.98 N60 ((B + 0.305)/B)² Kd (Se/25)`` for B > 1.22 m,
    - ``Kd = 1 + 0.33 Df/B ≤ 1.33``, Se in mm, qa in kPa, N60 the mean from Df to Df + 2B.

    With the Bangladesh consultant practice (``design.practice`` "bdConsultant") the same
    method in the SI form of Bowles (1996, eq. 4-12, F1 = 0.05, F2 = 0.08, F3 = 0.3 m, F4 =
    1.2 m) with the dilatancy-corrected N' of :mod:`saengine.soil.profile`, as the consultant
    sheets of common Dhaka soil reports print it:

    - ``qa = N'/0.05 Kd (Se/25)`` for B ≤ 1.2 m, ``qa = N'/0.08 ((B + 0.3)/B)² Kd (Se/25)``
      beyond, ``Kd = 1 + 0.33 Df/B ≤ 1.33``;
    - N' the mean over the influence zone from ``max(0, Df - B/2)`` to ``Df + 2B``, sampled
      every 0.5 m from 0.5 m below the top of the zone down to its bottom (inclusive); each
      sample takes the N' of the SPT row it lies in (the row from the test above, exclusive,
      to its own test, inclusive; below the last test the last row), rounded half up to a whole
      number as the sheets print it, whatever the soil.

    The check is applied, as in the textbook practice, when the zone holds granular soil; the
    value is given for every footing with SPT rows under it (``meyerhofBowles``) to compare
    with a consultant's table.

    The settlement of a clay is checked at the pressure actually adopted, by a loop: it starts
    from the lower of the shear and the Meyerhof-Bowles values (q0). When a cohesive layer lies
    within the zone the footing stresses under that pressure (down to where the 2:1 stress
    increase falls below 10 % of σ'v0), its settlement is computed
    (:mod:`saengine.soil.settlement`: immediate, plus consolidation where Cc and e0 are known);
    if it exceeds the allowable settlement, the highest lower pressure whose settlement is
    within it is found by bisection, and the zone at that pressure is checked again. The
    settlement grows with the pressure and jumps up where the zone first reaches a clay, so the
    bisected pressure settles at most the allowable amount whether the clay is still in its
    zone or not: the loop ends on the next pass (it is guarded at :data:`MAX_ITERATIONS`). The
    pressure is then either where the computed settlement equals the allowable one, or just
    below the one whose zone reaches the clay. When the settlement at the adopted pressure is
    within the allowable one, the settlement does not govern; the higher pressure at which it
    reaches it (by bisection, up to 5000 kPa) is given for the table. A clay only stressed by a
    pressure higher than the adopted one is not checked.

(c) ``qa = min(qa_shear, qa_settlement)``. There is no qa when a layer within B below the
    base has no strength (cu, or φ' or SPT), or when a cohesive layer in the stressed zone has
    neither a modulus nor Cc and e0 (its settlement would be unknown).

Units: m and kPa inside; the results give B, L, Df in mm and pressures in kPa.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from saengine.library.soil import Design
from saengine.soil.profile import GAMMA_W, Profile, SoilLayer
from saengine.soil.settlement import influence_depth, settlement


@dataclass
class Factors:
    nc: float
    nq: float
    ng: float


def factors(phi_deg: float) -> Factors:
    """Vesic's bearing capacity factors for a friction angle [°]."""
    phi = math.radians(phi_deg)
    if phi_deg < 1e-9:
        return Factors(5.14, 1.0, 0.0)
    nq = math.exp(math.pi * math.tan(phi)) * math.tan(math.pi / 4 + phi / 2) ** 2
    return Factors((nq - 1) / math.tan(phi), nq, 2 * (nq + 1) * math.tan(phi))


def ultimate(
    c: float, phi_deg: float, q: float, gamma: float, b: float, l_: float, df: float
) -> dict[str, float]:
    """qu [kPa] of the general bearing capacity equation, with its factors."""
    b, l_ = min(b, l_), max(b, l_)
    f = factors(phi_deg)
    phi = math.radians(phi_deg)
    ratio = b / l_
    sc = 1 + ratio * f.nq / f.nc
    sq = 1 + ratio * math.tan(phi)
    sg = max(0.6, 1 - 0.4 * ratio)
    k = df / b if df <= b else math.atan(df / b)
    dc = 1 + 0.4 * k
    dq = 1 + 2 * math.tan(phi) * (1 - math.sin(phi)) ** 2 * k
    qu = c * f.nc * sc * dc + q * f.nq * sq * dq + 0.5 * gamma * b * f.ng * sg
    return {
        "qu": qu,
        "Nc": f.nc,
        "Nq": f.nq,
        "Ngamma": f.ng,
        "sc": sc,
        "sq": sq,
        "sgamma": sg,
        "dc": dc,
        "dq": dq,
    }


def gamma_for_width(profile: Profile, layer: SoilLayer, df: float, b: float) -> float:
    """Unit weight of the ½γBNγ term with the water table correction."""
    moist, buoyant = layer.gamma, layer.gamma_sat - GAMMA_W
    wt = profile.water_table
    if wt is None or wt >= df + b:
        return moist
    if wt <= df:
        return buoyant
    return buoyant + (wt - df) / b * (moist - buoyant)


def shear(profile: Profile, b: float, l_: float, df: float, fs: float) -> dict[str, Any]:
    """Net allowable pressure against shear failure [kPa], from the weakest layer within B."""
    q_eff, q_total = profile.sigma_v_eff(df), profile.sigma_v(df)
    candidates: list[dict[str, Any]] = []
    skipped: list[str] = []
    unknown: list[str] = []
    for layer in profile.layers:
        if layer.bottom <= df + 1e-9 and layer is not profile.layers[-1]:
            continue
        if layer.top >= df + b:
            break
        name = f"layer {layer.index + 1} ({layer.soil_type})"
        if layer.behaviour == "rock":
            skipped.append(f"{name}: rock, not checked")
            continue
        gamma = gamma_for_width(profile, layer, df, b)
        options = []
        if layer.behaviour == "cohesive" and layer.cu is not None:
            r = ultimate(layer.cu, 0.0, q_eff, gamma, b, l_, df)
            options.append(("undrained", r, r["qu"] - q_eff))
        if layer.phi is not None and (layer.behaviour == "granular" or layer.phi > 0):
            r = ultimate(layer.c, layer.phi, q_eff, gamma, b, l_, df)
            options.append(("drained", r, r["qu"] - q_eff))
        if not options:
            unknown.append(f"{name}: no strength (cu or φ', or SPT to estimate them)")
            continue
        for mode, r, net in options:
            candidates.append(
                {
                    "layer": layer.index,
                    "mode": mode,
                    "qa": max(0.0, net) / fs,
                    "qu": r["qu"],
                    "factors": {k: round(v, 3) for k, v in r.items() if k != "qu"},
                    "c": layer.cu if mode == "undrained" else layer.c,
                    "phi": 0.0 if mode == "undrained" else layer.phi,
                    "label": name,
                }
            )
    if unknown:
        return {
            "qa": None,
            "notes": skipped
            + [f"{text}: it lies within B below the base, so there is no qa" for text in unknown],
        }
    if not candidates:
        return {"qa": None, "notes": skipped or ["no layer below the founding level"]}
    worst = min(candidates, key=lambda c: c["qa"])
    return {**worst, "q": q_eff, "sigma_v": q_total, "notes": skipped}


def meyerhof_bowles(n60: float, b: float, df: float, se: float) -> float:
    """Net allowable pressure [kPa] for a settlement ``se`` [mm] of a footing on sand."""
    kd = min(1.33, 1 + 0.33 * df / b)
    if b <= 1.22:
        return 19.16 * n60 * kd * se / 25
    return 11.98 * n60 * ((b + 0.305) / b) ** 2 * kd * se / 25


def meyerhof_bowles_si(n_prime: float, b: float, df: float, se: float) -> float:
    """Bowles' (1996) SI form with F1 = 0.05, F2 = 0.08, F3 = 0.3 m, F4 = 1.2 m [kPa]."""
    kd = min(1.33, 1 + 0.33 * df / b)
    if b <= 1.2:
        return n_prime / 0.05 * kd * se / 25
    return n_prime / 0.08 * ((b + 0.3) / b) ** 2 * kd * se / 25


#: Guard of the loop of :func:`settlement_controlled`; it converges in two passes.
MAX_ITERATIONS = 10

#: Spacing of the N' samples over the influence zone (consultant practice) [m].
ZONE_STEP = 0.5


def half_up(value: float) -> int:
    return math.floor(value + 0.5)


def zone_n_prime(profile: Profile, b: float, df: float) -> dict[str, Any] | None:
    """Mean N' over ``max(0, Df - B/2)`` to ``Df + 2B`` sampled every 0.5 m (consultant sheets)."""
    tests = [p for p in profile.spt if p.n_prime is not None]
    if not tests:
        return None
    top, bottom = max(0.0, df - b / 2), df + 2 * b
    samples: list[tuple[float, int]] = []
    k = 1
    while (z := top + k * ZONE_STEP) <= bottom + 1e-9:
        test = next((p for p in tests if z <= p.depth + 1e-9), tests[-1])
        assert test.n_prime is not None
        samples.append((z, half_up(test.n_prime)))
        k += 1
    if not samples:
        return None
    return {
        "N": sum(n for _, n in samples) / len(samples),
        "count": len(samples),
        "top": top,
        "bottom": bottom,
        "samples": samples,
    }


def settlement_controlled(
    profile: Profile, b: float, l_: float, df: float, se: float, upper: float
) -> dict[str, Any]:
    """Net pressure [kPa] limiting the settlement to ``se`` [mm]."""
    results: list[tuple[str, float]] = []
    notes: list[str] = []
    zone = [
        layer
        for layer in profile.layers
        if layer.bottom > df and layer.top < df + 2 * b and layer.behaviour == "granular"
    ]
    consultant: dict[str, Any] | None = None
    if profile.practice == "bdConsultant":
        consultant = zone_n_prime(profile, b, df)
        if consultant is not None:
            consultant["qa"] = meyerhof_bowles_si(consultant["N"], b, df, se)
    if zone and profile.practice == "bdConsultant":
        if consultant is not None:
            results.append(
                (
                    (
                        f"Meyerhof-Bowles (consultant practice), N' = {consultant['N']:.2f} (mean "
                        f"of {consultant['count']} samples every 0.5 m from "
                        f"{consultant['top']:.2f} to {consultant['bottom']:.2f} m)"
                    ),
                    consultant["qa"],
                )
            )
        else:
            notes.append("no SPT below the founding level for the settlement check of the sand")
    elif zone:
        tests = [
            p
            for p in profile.spt_in(df, df + 2 * b)
            if p.layer is not None and p.layer.behaviour == "granular"
        ]
        if not tests:
            below = [p for p in profile.spt if p.depth >= df]
            tests = below[:1]
        if tests:
            n60 = sum(p.n60 for p in tests) / len(tests)
            results.append(
                (
                    (
                        f"Meyerhof-Bowles, N60 = {n60:.1f} (mean of {len(tests)} test(s) from "
                        "Df to Df + 2B)"
                    ),
                    meyerhof_bowles(n60, b, df, se),
                )
            )
        else:
            notes.append("no SPT below the founding level for the settlement check of the sand")
    # The settlement of a clay is checked at the pressure actually adopted (see the module
    # docstring): the lower of the shear and the Meyerhof-Bowles values to start with.
    adopted = min([upper, *(value for _, value in results)])

    def clays(q: float) -> list[SoilLayer]:
        depth = influence_depth(profile, b, l_, df, q)
        return [
            layer
            for layer in profile.layers
            if layer.behaviour == "cohesive" and layer.bottom > df and layer.top < df + depth
        ]

    def total(q: float) -> float:
        return settlement(profile, b, l_, df, q)["total"]

    def limit(lo: float, hi: float) -> float:
        """Bisection between lo (settles at most se) and hi (more): the highest such pressure."""
        for _ in range(60):
            mid = (lo + hi) / 2
            if total(mid) > se:
                hi = mid
            else:
                lo = mid
            if hi - lo < 0.1:
                break
        return lo

    checked: list[SoilLayer] = []
    reduced = False
    q = adopted
    for _ in range(MAX_ITERATIONS):
        cohesive = clays(q)
        unknown = [
            layer for layer in cohesive if not layer.E and (layer.cc is None or layer.e0 is None)
        ]
        for layer in unknown:
            notes.append(
                f"layer {layer.index + 1} ({layer.soil_type}): no modulus, Cc or e0, so its "
                "settlement cannot be computed: no settlement-controlled pressure"
            )
        if unknown:
            return {
                "qa": None,
                "method": None,
                "notes": notes,
                "incomplete": True,
                "consultant": consultant,
            }
        if not cohesive:
            break
        checked = cohesive
        if total(q) <= se:
            break
        # Bisection for the highest pressure below q whose settlement is within se. total(q)
        # grows with q and jumps up where the zone first reaches a clay; lo always settles at
        # most se (total(0) = 0), so the next pass stops: the sequence of pressures only falls.
        q, reduced = limit(0.0, q), True
    if checked:
        result = settlement(profile, b, l_, df, q)
        names = ", ".join(f"layer {layer.index + 1} ({layer.soil_type})" for layer in checked)
        kinds = "immediate + consolidation" if result["consolidation"] > 0.05 else "immediate"
        still = clays(q)
        if not reduced:
            # Within se at the adopted pressure: the settlement does not govern. Its own limit
            # (above q, for the table) is where the settlement reaches se, as far as 5000 kPa.
            lo, hi = q, max(q, 50.0)
            while total(hi) <= se and hi < 5000.0:
                lo, hi = hi, hi * 2
            if total(hi) <= se:
                q = hi
                text = f"computed settlement below {se:g} mm up to {hi:.0f} kPa, {names} stressed"
            else:
                q = limit(lo, hi)
                text = (
                    f"computed settlement ({kinds}) = {result['total']:.1f} mm ≤ {se:g} mm at "
                    f"the adopted {adopted:.0f} kPa ({names} in the stressed zone); {se:g} mm at "
                    f"{q:.0f} kPa"
                )
        elif still:
            text = f"computed settlement ({kinds}) = {se:g} mm, {names} in the stressed zone"
        else:
            text = (
                f"computed settlement: above {q:.0f} kPa the stressed zone reaches {names} and "
                f"the settlement exceeds {se:g} mm"
            )
        results.append((text, q))
    if not results:
        return {"qa": None, "method": None, "notes": notes, "consultant": consultant}
    method, qa = min(results, key=lambda r: r[1])
    return {"qa": qa, "method": method, "notes": notes, "consultant": consultant}


def allowable(profile: Profile, b: float, l_: float, df: float) -> dict[str, Any]:
    """qa [kPa] of a footing B × L [m] founded Df [m] below the borehole's ground."""
    design = profile.design
    s = shear(profile, b, l_, df, design.factorOfSafety)
    upper = s["qa"] if s["qa"] is not None else 1000.0
    t = settlement_controlled(profile, b, l_, df, design.allowableSettlement, upper)
    values = [v for v in (s["qa"], t["qa"]) if v is not None]
    # Without the strength, or with a clay whose settlement cannot be computed, there is no qa.
    qa = min(values) if values and s["qa"] is not None and not t.get("incomplete") else None
    governs = None
    if qa is not None:
        governs = "shear" if s["qa"] is not None and qa == s["qa"] else "settlement"
    shear_text = None
    if s["qa"] is not None:
        shear_text = (
            f"{s['label']}, {s['mode']}: qu = {s['qu']:.0f} kPa, qa = (qu - σ'v)/FS"
            if s["mode"] == "drained"
            else f"{s['label']}, undrained: cu = {s['c']:.0f} kPa, qa = cu Nc sc dc/FS"
        )
    return {
        "B": round(b * 1e3),
        "L": round(l_ * 1e3),
        "Df": round(df * 1e3),
        "qa_shear": None if s["qa"] is None else round(s["qa"], 1),
        "qa_settlement": None if t["qa"] is None else round(t["qa"], 1),
        "qa": None if qa is None else round(qa, 1),
        "governs": governs,
        "shear": shear_text,
        "settlement": t["method"],
        "meyerhofBowles": _consultant_json(t.get("consultant")),
        "notes": s["notes"] + t["notes"],
    }


def _consultant_json(info: dict[str, Any] | None) -> dict[str, Any] | None:
    if info is None:
        return None
    return {
        "N": round(info["N"], 2),
        "count": info["count"],
        "top": round(info["top"] * 1e3),
        "bottom": round(info["bottom"] * 1e3),
        "qa": round(info["qa"], 1),
    }


def table(profile: Profile) -> list[dict[str, Any]]:
    """qa of square footings for the report's widths and founding depths."""
    design = profile.design
    rows = []
    for df in design.tableDepths:
        for b in design.tableWidths:
            rows.append(allowable(profile, b / 1e3, b / 1e3, df / 1e3))
    return rows


_SHEAR = (
    "qa = min(shear, settlement). Shear: general bearing capacity equation, Vesic (1975) "
    "factors, De Beer shape and Hansen depth factors, water table correction; undrained clay "
    "qu - q = cu Nc sc dc; the weakest layer within B below the base (a layer there with no "
    "strength data withholds qa); FS on the net value qu - σ'v. "
)
_SETTLEMENT = {
    "textbook": (
        "Settlement: Meyerhof (1965) as modified by Bowles (1977) from N60 for sand "
        "(19.16 N60 Kd for B ≤ 1.22 m, 11.98 N60 ((B + 0.305)/B)² Kd beyond, × Se/25); "
    ),
    "bdConsultant": (
        "Settlement (Bangladesh consultant practice): Meyerhof-Bowles with N' (N'/0.05 Kd for "
        "B ≤ 1.2 m, N'/0.08 ((B + 0.3)/B)² Kd beyond, × Se/25), N' the mean of the "
        "dilatancy-corrected (N1)60 sampled every 0.5 m from max(0, Df - B/2) to Df + 2B; "
    ),
}
_COMPUTED = (
    "computed settlement (Schmertmann 1978, elastic and 1D consolidation) when clay is within "
    "the stressed zone under the adopted pressure (the lower of the above, reduced until the "
    "settlement is within the allowable value, the zone checked again at each pressure). "
    "Square footings; net pressures (gross minus the overburden)."
)

#: The textbook method (kept for the callers that name it without the design options).
METHOD = _SHEAR + _SETTLEMENT["textbook"] + _COMPUTED


def method_text(design: Design) -> str:
    """How qa is worked out with the report's design options, with the settlement criterion."""
    from saengine.soil.settlement import permissible_text

    return (
        _SHEAR
        + _SETTLEMENT[design.practice]
        + _COMPUTED
        + f" Settlement criterion of qa: {design.allowableSettlement:g} mm (design option "
        + f"allowable settlement); {permissible_text('isolated')}."
    )

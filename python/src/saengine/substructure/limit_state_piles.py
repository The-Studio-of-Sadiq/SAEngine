"""Piles by limit states (alpha 9 C5b): the design resistance of a pile cap's piles from the
pack's correlation factors ξ (method ``correlationFactors`` of ``geotechnicalMethods``) and
the design approach's pile resistance sets, in place of the parent pack's factor of safety.
The functions are in :mod:`saengine.substructure.limit_state_geotechnics`. Units: kN, m.

- Characteristic resistance: from the pile type's static load tests where they reached a
  failure load (Rc,k = min(mean/ξ1, min/ξ2)); else from ground tests: the calculated
  resistance Rc,cal of the pile at every borehole of the soil report (SAEngine's static
  method, :func:`saengine.substructure.piles.single_pile` without factors), n = the
  boreholes, Rc,k = min(mean/ξ3, min/ξ4), split into base and shaft by their mean shares.
- Design resistance per combination of the design approach: Rc,d = Rb,k/γb + Rs,k/γs (load
  tests: Rc,k/γt), the tension Rt,d = Rt,k/γs,t with Rt,k from the shaft share of the uplift.
- Actions: the pile reactions of the rigid cap under the strength combinations of the
  combination's action set (as :mod:`saengine.substructure.limit_state_footings`), the cap and
  the soil over it × γG, the pile's own weight × γG on the action side.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.design import method_selection
from saengine.substructure import limit_state_geotechnics as lsg


def selected() -> bool:
    """True when the pack in force designs piles with correlation factors and resistance sets."""
    return method_selection.geotechnical("piles") == "correlationFactors"


def characteristic(
    calculated: list[tuple[float, float]], tests: dict[str, Any] | None
) -> dict[str, Any]:
    """Rc,k [kN] and its base and shaft parts from ``calculated`` (Rb,cal, Rs,cal) per borehole,
    or from the load tests' summary (``tests["limitState"]``) where it is given."""
    if tests and tests.get("limitState"):
        rck = float(tests["limitState"]["Rck"])
        return {"Rck": rck, "Rbk": None, "Rsk": None, "source": "load tests", "n": tests["limitState"]["tests"],
                "xi": (tests["limitState"]["xi1"], tests["limitState"]["xi2"])}  # fmt: skip
    totals = [b + s for b, s in calculated]
    n = len(totals)
    xi3, xi4 = lsg.correlation_factors(n, load_tests=False)
    mean = sum(totals) / n
    rck = min(mean / xi3, min(totals) / xi4)
    base_share = (sum(b for b, _ in calculated) / n) / mean if mean > 0 else 0.0
    return {
        "Rck": rck,
        "Rbk": rck * base_share,
        "Rsk": rck * (1 - base_share),
        "source": "ground tests",
        "n": n,
        "xi": (xi3, xi4),
    }


def cap_rows(
    ctx: Any,
    placed: Any,
    spec: Any,
    pile_type: Any,
    method: str,
    construction: Any,
    unit_weight: float,
    tests: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[str]] | None:
    """The compression and tension rows of a cap's piles in each combination of the design
    approach; None without boreholes to calculate from."""
    from saengine.design.check import _check
    from saengine.substructure.limit_state_footings import _combination_sets
    from saengine.substructure.pilecap import pile_reactions
    from saengine.substructure.piles import FactorsOfSafety, profiles_of, single_pile
    from saengine.substructure.shallow import _actions, combination_loads

    profiles, report, _problems = profiles_of(ctx.soil_text)
    if not profiles:
        return None
    kind = pile_type.kind
    unity = FactorsOfSafety(1.0, 1.0, 1.0, 1.0, False)
    calculated: list[tuple[float, float]] = []
    shafts: list[float] = []
    weight = 0.0
    for profile in profiles:
        head = max((report.ground_level(profile.borehole) - placed.founding_level) / 1e3, 0.0)
        try:
            found = single_pile(
                profile, kind, pile_type.diameter / 1e3, pile_type.length / 1e3, head, method,
                unity, unit_weight, construction, getattr(pile_type, "shape", None),
            )  # fmt: skip
        except ValueError:
            continue
        calculated.append((float(found["Qb"]), float(found["Qs"])))
        shafts.append(float(found["Qs"]))
        weight = float(found["W"])
    if not calculated:
        return None
    rk = characteristic(calculated, tests)
    r = lsg.rules()
    actions = _actions(ctx.loads, placed)
    rows = []
    t_share = None
    for label, combo, listed, _favourable in _combination_sets(ctx.loads):
        rset = combo.pileResistances or combo.resistances
        a_set = r.actions[combo.actions]
        if rk["Rbk"] is not None:
            rcd = lsg.pile_design_resistance(rk["Rbk"], kind, rset, "base") + (
                lsg.pile_design_resistance(rk["Rsk"], kind, rset, "shaft")
            )
        else:
            rcd = lsg.pile_design_resistance(rk["Rck"], kind, rset, "total")
        loads = combination_loads(ctx.loads, placed, listed, actions)
        worst_c, worst_t = (-math.inf, None), (math.inf, None)
        for name, column_loads in loads.items():
            reactions, _ = pile_reactions(
                spec, column_loads, a_set.permanentUnfavourable * spec.weight
            )
            if reactions.max() > worst_c[0]:
                worst_c = (float(reactions.max()), name)
            fav = a_set.permanentFavourable / a_set.permanentUnfavourable
            low = float(reactions.min()) - (
                1 - fav
            ) * a_set.permanentUnfavourable * spec.weight / max(len(spec.piles), 1)
            if low < worst_t[0]:
                worst_t = (low, name)
        if worst_c[1] is not None:
            fcd = worst_c[0] / 1e3 + a_set.permanentUnfavourable * weight
            xi = rk["xi"]
            rows.append(
                _check(
                    f"Pile resistance, compression ({label})",
                    fcd,
                    rcd,
                    "kN",
                    worst_c[1],
                    f"Rc,k = {rk['Rck']:.0f} kN from {rk['n']} {rk['source']} (ξ = {xi[0]:.2f}, "
                    f"{xi[1]:.2f}), set {rset}; Fc,d with the pile's weight {weight:.0f} kN × γG"
                    + code_context.cited(
                        "geotechnicalMethods",
                        "pileLoadTests" if rk["source"] == "load tests" else "pileGroundTests",
                        sep="; ",
                    ),
                )
            )
        if worst_t[1] is not None and worst_t[0] < 0 and shafts:
            if t_share is None:
                from saengine.substructure.piles import uplift_skin

                t_share = uplift_skin()
                xi3, xi4 = lsg.correlation_factors(len(shafts), load_tests=False)
                mean = sum(shafts) / len(shafts)
                t_share = t_share * min(mean / xi3, min(shafts) / xi4)
            rtd = lsg.pile_design_resistance(t_share, kind, rset, "tension") + weight
            rows.append(
                _check(
                    f"Pile resistance, tension ({label})",
                    -worst_t[0] / 1e3,
                    rtd,
                    "kN",
                    worst_t[1],
                    f"Rt,k = {t_share:.0f} kN (the shaft's uplift share, ξ3, ξ4), set {rset}; "
                    "the pile's weight resists, permanent actions favourable"
                    + code_context.cited("geotechnicalMethods", "pileTension", sep="; "),
                )
            )
    notes = [
        (
            f"{spec.id}: the piles by limit states, design approach {r.designApproach}; the "
            "allowable pile load rows are reported only"
        )
    ]
    return rows, notes

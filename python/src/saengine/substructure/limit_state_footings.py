"""Spread footings by limit states (alpha 9 C5b): the bearing and sliding resistance of the
pack's ``geotechnicalMethods`` (method ``effectiveArea`` of ``bearing``, ``interfaceFriction``
of ``sliding``) in each combination of the design approach in force, in place of the parent
pack's allowable bearing pressure. The functions are in
:mod:`saengine.substructure.limit_state_geotechnics`; this module puts a footing's actions and
soil into them. Units here: N, mm (the footing's), kN, kPa, m (the resistances').

- Soil: the characteristic φ'k, c'k, cu,k and γ of the layer at the founding level of the
  borehole nearest the footing (SAEngine practice, overridable by the soil report); drained
  where the layer gives φ', undrained where it gives cu (both where both), by the pack's
  ``footings.drained``.
- Actions: the project's strength combinations (the pack's EN 1990 set: A1) for a combination
  with set A1, and the same with the permanent cases (D, SD, F, H) × γG(set) / γG(A1) and the
  others × γQ(set) / γQ(A1) for another set (A2); combinations with earthquake as they are (the
  seismic design situation). The footing and the soil over it are permanent, × γG(set).
- Bearing: Vd against Rd = R / γR,v on the effective base B' L' of the resultant's
  eccentricities, q' the effective overburden at the base, the horizontal force for the
  inclination factors.
- Sliding: Hd against Rd of the base (drained with φ'cv,k = share × φ'k, cast in place;
  undrained with cu, at most 0.4 Vd where water reaches the base), Vd with the permanent
  actions favourable (× γG,inf).
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.design import method_selection
from saengine.substructure import limit_state_geotechnics as lsg

#: The analysis cases taken as permanent actions (SAEngine's case ids).
PERMANENT = frozenset({"D", "SD", "F", "H"})
GAMMA_W = 9.81  # kN/m³


def selected() -> bool:
    """True when the pack in force designs spread footings by limit states."""
    return method_selection.geotechnical("bearing") == "effectiveArea"


def _earthquake(factors: dict[str, float]) -> bool:
    return any(case.startswith("E") and abs(f) > 0 for case, f in factors.items())


#: Gravity variable cases left out where the permanent actions are favourable (sliding).
GRAVITY_VARIABLE = frozenset({"L", "Lr", "S"})


def _combination_sets(loads: Any) -> list[tuple[str, Any, list[Any], list[Any]]]:
    """(label, DA combination, the factored combinations of its action set, their twins with
    the permanent actions favourable and no gravity variable action) of the design approach in
    force, formed once per pack (they are kept: :func:`saengine.substructure.shallow.
    combination_loads` caches by the list)."""
    cache = loads.__dict__.setdefault("_limit_state_footings", {})
    pack = code_context.current().id
    if pack in cache:
        return cache[pack]
    r = lsg.rules()
    combos = lsg.combinations()
    reference = r.actions.get("A1") or next(iter(r.actions.values()))
    out = []
    for k, combo in enumerate(combos):
        label = r.designApproach + (f"-C{k + 1}" if len(combos) > 1 else "")
        own = r.actions[combo.actions]
        g = own.permanentUnfavourable / reference.permanentUnfavourable
        q = own.variableUnfavourable / reference.variableUnfavourable
        listed, favourable = [], []
        for name, factors in loads.strength:
            if _earthquake(factors):
                scaled = dict(factors)
            else:
                scaled = {c: f * (g if c in PERMANENT else q) for c, f in factors.items()}
            listed.append((f"{label}: {name}", scaled))
            favourable.append(
                (
                    f"{label}: {name}",
                    {
                        c: (own.permanentFavourable if c in PERMANENT else f)
                        for c, f in scaled.items()
                        if c not in GRAVITY_VARIABLE
                    },
                )
            )
        out.append((label, combo, listed, favourable))
    cache[pack] = out
    return out


def _soil(ctx: Any, placed: Any, bearing: Any) -> tuple[Any, float, Any] | None:
    """(the founding layer, its depth z below the borehole's ground [m], the profile)."""
    from saengine.substructure.piles import nearest_profile, profiles_of

    profiles, _report, _problems = profiles_of(getattr(ctx, "soil_text", None))
    if not profiles:
        return None
    profile, _distance = nearest_profile(profiles, float(placed.center[0]), float(placed.center[1]))
    z = max(profile.ground_level - placed.founding_level / 1e3, 0.0)
    layer = profile.layer_at(z)
    if layer is None:
        return None
    return layer, z, profile


def footing_rows(
    ctx: Any,
    foundation: Any,
    placed: Any,
    bearing: Any,
    own_weight: float,
) -> tuple[list[dict[str, Any]], list[str]] | None:
    """The bearing and sliding rows of a footing in each combination of the design approach;
    None when the soil report gives no strength parameters at the founding level (the parent
    pack's allowable bearing then stays). ``own_weight``: the footing and the soil over it
    [N/mm² of base]."""
    from saengine.design.check import _check
    from saengine.substructure.shallow import (
        _actions,
        _eccentricity,
        combination_loads,
        footing_horizontal,
    )

    found = _soil(ctx, placed, bearing)
    if found is None:
        return None
    layer, z, profile = found
    r = lsg.rules()
    rules = r.footings
    mode = rules.drained if rules is not None else "auto"
    cases = []
    if layer.phi and mode in ("auto", "drained"):
        cases.append(True)
    if layer.cu and mode in ("auto", "undrained"):
        cases.append(False)
    if not cases:
        return None
    spec = placed.spec
    b_m, l_m = spec.width / 1e3, spec.length / 1e3
    area = b_m * l_m
    water = profile.water_table
    below = water is not None and water <= z + min(b_m, l_m)
    gamma_eff = (layer.gamma_sat - GAMMA_W) if below else layer.gamma
    q_eff = profile.sigma_v_eff(z)
    actions = _actions(ctx.loads, placed)
    weight_kn = own_weight * spec.length * spec.width / 1e3
    rows: list[dict[str, Any]] = []
    clause_bearing = code_context.cite("geotechnicalMethods", "bearing")
    clause_sliding = code_context.cite("geotechnicalMethods", "sliding")
    for label, combo, listed, favourable in _combination_sets(ctx.loads):
        a_set = r.actions[combo.actions]
        loads = combination_loads(ctx.loads, placed, listed, actions)
        loads_fav = combination_loads(ctx.loads, placed, favourable, actions)
        horizontal = footing_horizontal(ctx.loads, placed, listed)
        worst_b = worst_s = None
        for drained in cases:
            params = lsg.design_parameters(
                layer.phi or 0.0, layer.c or 0.0, layer.cu, layer.gamma, combo.materials
            )
            for name, column_loads in loads.items():
                g_factor = (
                    1.0 if _earthquake(dict(listed).get(name, {})) else a_set.permanentUnfavourable
                )
                total, eu, ev = _eccentricity(spec, column_loads, 0.0)
                vd = total / 1e3 + g_factor * weight_kn
                hd = horizontal.get(name, 0.0) / 1e3
                if vd <= 0:
                    continue
                share = (total / 1e3) / vd if vd else 1.0
                e_b, e_l = abs(ev) * share / 1e3, abs(eu) * share / 1e3
                res = lsg.bearing_resistance(
                    b_m, l_m, params, q_eff, gamma_eff, vd, hd, e_b, e_l, 0.0, drained
                )
                rd = lsg.bearing_design(res["R"], combo.resistances)
                ratio = vd / rd if rd > 0 else math.inf
                if worst_b is None or ratio > worst_b[0]:
                    worst_b = (ratio, vd, rd, name, drained, res, e_b, e_l)
                # Sliding with the permanent actions favourable.
                fav_total = _eccentricity(spec, loads_fav.get(name, column_loads), 0.0)[0]
                v_fav = fav_total / 1e3 + a_set.permanentFavourable * weight_kn
                if hd > 0 and r.sliding is not None:
                    phi_cv = (layer.phi or 0.0) * (rules.phiCvShare if rules else 1.0)
                    rs = lsg.sliding_resistance(
                        v_fav,
                        combo.resistances,
                        phi_cv if drained and layer.phi else None,
                        combo.materials,
                        rules.castInPlace if rules else True,
                        res.get("area") or area,
                        layer.cu,
                        rules.waterAtInterface if rules else True,
                    )
                    s_ratio = hd / rs if rs > 0 else math.inf
                    if worst_s is None or s_ratio > worst_s[0]:
                        worst_s = (s_ratio, hd, rs, name, drained)
        if worst_b is not None:
            ratio, vd, rd, name, drained, res, e_b, e_l = worst_b
            rows.append(
                _check(
                    f"Bearing resistance ({label})",
                    vd,
                    rd,
                    "kN",
                    name,
                    f"{'drained' if drained else 'undrained'}, sets {combo.actions} + "
                    f"{combo.materials} + {combo.resistances}; B' x L' from eB = {e_b:.2f} m, "
                    f"eL = {e_l:.2f} m, A' = {res['area']:.2f} m², R/A' = {res['q']:.0f} kPa, "
                    f"q' = {q_eff:.0f} kPa, γ' = {gamma_eff:.1f} kN/m³; φ'k = "
                    f"{layer.phi or 0:g}°, c'k = {layer.c or 0:g} kPa, cu,k = {layer.cu or 0:g} kPa "
                    f"(layer {layer.index + 1} at {z:.2f} m)"
                    + (f" ({clause_bearing})" if clause_bearing else ""),
                    utilisation=ratio,
                )
            )
        if worst_s is not None:
            ratio, hd, rs, name, drained = worst_s
            rows.append(
                _check(
                    f"Sliding resistance ({label})",
                    hd,
                    rs,
                    "kN",
                    name,
                    f"{'drained, δ = φ' + chr(39) + 'cv,d' if drained else 'undrained'}, sets "
                    f"{combo.actions} + {combo.materials} + {combo.resistances}; permanent "
                    "actions favourable" + (f" ({clause_sliding})" if clause_sliding else ""),
                    utilisation=ratio,
                )
            )
    notes = [
        f"{spec.id}: bearing and sliding by limit states, design approach {r.designApproach}"
        + code_context.cited("geotechnicalMethods", "designApproach", sep=" (")
        + (")" if code_context.cite("geotechnicalMethods", "designApproach") else "")
        + "; the allowable pressure row is reported only (serviceability indication)"
    ]
    return rows, notes


def method_lines() -> list[str]:
    """The design report's method lines of spread footings by limit states."""
    r = lsg.rules()
    combos = ", ".join(f"{c.actions} + {c.materials} + {c.resistances}" for c in lsg.combinations())
    return [
        (
            f"Spread footings by limit states, design approach {r.designApproach} ({combos}; "
            f"{code_context.cite('geotechnicalMethods', 'designApproach')}): the bearing "
            "resistance on the effective base by the general equation with the founding "
            "layer's characteristic parameters of the nearest borehole factored by the set M, "
            f"Rd = R/γR,v ({code_context.cite('geotechnicalMethods', 'bearing')}); sliding "
            f"Rd = V'd tan δd/γR,h or A' cu,d/γR,h ({code_context.cite('geotechnicalMethods', 'sliding')}). "
            "The allowable pressure of the parent pack (with its settlement limit) is reported "
            "beside them as a serviceability indication; settlement is SAEngine's method."
        )
    ]

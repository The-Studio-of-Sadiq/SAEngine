"""Capacity design of foundations (method ``overstrengthFactor`` of the pack's
``seismic.foundationCapacity``; alpha 9 C5c, EN 1998-1 4.4.2.6 type).

The foundations' strength combinations with earthquake take EFd = EF,G + γRd Ω EF,E: the
earthquake cases' factors × γRd Ω, γRd by the behaviour factor q (``gammaLow`` up to
``qLimit``, ``gammaHigh`` above); γRd Ω at most q. A pack without the rule (the default) leaves
the combinations as they are.

Ω (alpha 9 C26, owner decision 2026-11-04, EN 1998-1 4.4.2.6(2)P and (3)): per foundation,
from the dissipative zone at the base of the column it carries, Ω = MRd / MEd of the column's
base section in the seismic design situation (the least over the strength combinations with
earthquake: the zone's governing ratio; MRd at the combination's axial force, from the column's
reinforcement), at least 1 and with γRd Ω at most q. A base without such a ratio (a wall, a
steel column, a column without bars or forces) takes the pack's ``omega`` (or the project's
override) and, without one, q (the action effects of the elastic response, which the rule need
not exceed: SAEngine practice, on the safe side). The earthquake cases of the strength
combinations become their capacity-design copies (:data:`SUFFIX`), whose support reactions are
the case's times each base's γRd Ω: every reader of the bases' loads (footings, caps, rafts,
piles) sees each foundation's own factor, the service combinations the cases as analysed.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from saengine.codes import context as code_context

#: The earthquake load cases of the analysis whose factors are scaled.
EARTHQUAKE = ("EX", "EY", "EXP", "EXN", "EYP", "EYN", "RX", "RY", "EV")
#: Alpha 9 C26: the name of an earthquake case's capacity-design copy ("EX" -> "EX·γRdΩ").
SUFFIX = "·γRdΩ"


def rules() -> Any | None:
    found = getattr(code_context.table("seismic"), "foundationCapacity", None)
    return found if found is not None and found.method == "overstrengthFactor" else None


def _gamma_q(settings: Any, r: Any) -> tuple[float, float]:
    """(γRd, q) of the project under rule ``r``."""
    from saengine.library.settings import derived

    q = float(derived(settings).get("R") or 1.0)
    return (r.gammaLow if q <= r.qLimit else r.gammaHigh), q


def factor(settings: Any) -> tuple[float, str] | None:
    """(γRd Ω, how) of the project with the pack's (or the elastic) Ω, the value of a base
    without its own ratio; None without the pack's rule."""
    r = rules()
    if r is None:
        return None
    gamma, q = _gamma_q(settings, r)
    omega = r.omega if r.omega is not None else q
    value = min(gamma * omega, q)
    how = (
        f"EFd = EF,G + γRd Ω EF,E, γRd = {gamma:g} (q = {q:g}), Ω = MRd/MEd of the column "
        "at each base (at least 1), else "
        + (f"{omega:g}" if r.omega is not None else "q (the elastic response, on the safe side)")
        + f", γRd Ω = {value:.3f} at most q"
    )
    clause = code_context.cite("seismic", "foundationCapacity")
    return value, how + (f" ({clause})" if clause else "")


def capacity_combinations(
    strength: list[tuple[str, dict[str, float]]], settings: Any
) -> tuple[list[tuple[str, dict[str, float]]], str | None]:
    """The strength combinations with their earthquake factors × γRd Ω (the value of
    :func:`factor`), and the note; as they are without the rule."""
    found = factor(settings)
    if found is None:
        return strength, None
    value, how = found
    out = []
    for name, factors in strength:
        if any(factors.get(c) for c in EARTHQUAKE):
            scaled = {k: (v * value if k in EARTHQUAKE else v) for k, v in factors.items()}
            out.append((name, scaled))
        else:
            out.append((name, factors))
    return out, how


# ─────────────────────────── Ω from the dissipative members (alpha 9 C26) ───────────────────────────


def base_omega(
    surface: Any, rotation: float, actions: list[tuple[float, float, float]]
) -> float | None:
    """Ω = MRd / MEd of a column base section (:class:`saengine.design.rc.InteractionSurface`,
    the column turned by ``rotation`` [°]) under ``actions`` (Pu [N], compression positive, and
    the global Mx, My [N·mm] of each strength combination with earthquake): the least ratio
    over the combinations, the larger of the two ways the global moments may map onto the
    section's axes (on the safe side); None when no combination bends the base."""
    turn = math.radians(rotation)
    c, s = math.cos(turn), math.sin(turn)
    least: float | None = None
    for pu, mx, my in actions:
        local = (c * mx + s * my, -s * mx + c * my)
        demand = math.hypot(*local)
        if demand <= 1.0:  # under 1 N·mm: no bending
            continue
        ratios = []
        for a, b in (local, local[::-1]):
            capacity = surface.moment_capacity(pu, math.atan2(abs(b), abs(a)))
            if capacity > 0:
                ratios.append(capacity / demand)
        if not ratios:
            continue
        ratio = max(ratios)
        least = ratio if least is None else min(least, ratio)
    return least


def member_omegas(
    loads: Any, strength: list[tuple[str, dict[str, float]]], objects: Any, materials: Any
) -> dict[str, float]:
    """Ω of each column base of ``loads`` (:class:`saengine.substructure.loads.BaseLoads`) from
    its column's reinforcement and its base forces under the (unscaled) strength combinations
    with earthquake (:func:`base_omega`); the bases without one are left out."""
    from saengine.design.rc import DesignError, InteractionSurface, section_of
    from saengine.library.bim import ColumnElement

    seismic = [f for _, f in strength if any(f.get(c) for c in EARTHQUAKE)]
    if not seismic:
        return {}
    types = {o.id: o for o in getattr(objects, "objects", [])}
    mats = {m.id: m for m in getattr(materials, "materials", [])}
    surfaces: dict[str, Any] = {}
    out: dict[str, float] = {}
    for base_id, base in loads.bases.items():
        element = base.element
        if not isinstance(element, ColumnElement) or len(base.nodes) != 1:
            continue
        object_type = types.get(element.type)
        reinforcement = getattr(object_type, "reinforcement", None)
        if object_type is None or reinforcement is None or not reinforcement.longitudinal:
            continue
        concrete, bars = mats.get(object_type.material), mats.get(reinforcement.material)
        if concrete is None or not getattr(concrete, "concrete", None):
            continue
        if bars is None or getattr(bars, "steel", None) is None:
            continue
        if element.type not in surfaces:
            try:
                section = section_of(
                    object_type.profile,
                    reinforcement,
                    concrete.concrete.fc,
                    bars.steel.fy,
                    bars.mechanical.E or 200_000.0,
                    concrete.concrete.maxAggregate,
                )
                surfaces[element.type] = InteractionSurface(section)
            except DesignError:
                surfaces[element.type] = None
        surface = surfaces[element.type]
        if surface is None:
            continue
        node = base.nodes[0][0]
        actions = []
        for factors in seismic:
            r = loads.reaction(node, factors)  # on the support: + up = the column in compression
            actions.append((float(r[2]), float(r[3]) * 1e3, float(r[4]) * 1e3))
        found = base_omega(surface, float(getattr(element, "rotation", 0.0) or 0.0), actions)
        if found is not None:
            out[base_id] = found
    return out


def apply_member_omegas(loads: Any, objects: Any, materials: Any, settings: Any) -> str | None:
    """Alpha 9 C26: each base's γRd Ω from its column (:func:`member_omegas`) in place of the
    single value :func:`capacity_combinations` gave: the earthquake cases of ``loads.strength``
    become their capacity-design copies (:data:`SUFFIX`) whose reactions are the case's ×
    min(γRd max(Ω, 1), q) of the base the node carries (the single value at other nodes).
    ``loads.capacity`` keeps the factors; returns the note, None without the pack's rule or
    without the unscaled combinations (``loads.unscaled_strength``)."""
    r = rules()
    unscaled = getattr(loads, "unscaled_strength", None)
    found = factor(settings)
    if r is None or found is None or not unscaled:
        return None
    gamma, q = _gamma_q(settings, r)
    value, how = found
    try:
        omegas = member_omegas(loads, unscaled, objects, materials)
    except Exception as error:  # noqa: BLE001 - the single value stands
        return f"{how}; Ω of the columns not found ({error}): the single value used"
    per_base = {b: min(gamma * max(o, 1.0), q) for b, o in omegas.items()}
    node_factor: dict[int, float] = {}
    for base_id, base in loads.bases.items():
        for node, _xyz in base.nodes:
            node_factor[node] = per_base.get(base_id, value)
    for case in EARTHQUAKE:
        reactions = loads.cases.get(case)
        if reactions is None:
            continue
        loads.cases[case + SUFFIX] = {
            node: np.asarray(reaction, dtype=float) * node_factor.get(node, value)
            for node, reaction in reactions.items()
        }
    strength = []
    for name, factors in unscaled:
        if any(factors.get(c) for c in EARTHQUAKE):
            strength.append(
                (name, {(k + SUFFIX if k in EARTHQUAKE else k): v for k, v in factors.items()})
            )
        else:
            strength.append((name, factors))
    loads.strength = strength
    loads.capacity = {"value": value, "gamma": gamma, "q": q, "omega": omegas, "factor": per_base}
    if omegas:
        least, most = min(omegas.values()), max(omegas.values())
        how += f"; Ω of the columns {least:.2f}-{most:.2f} ({len(omegas)} bases)"
    return how

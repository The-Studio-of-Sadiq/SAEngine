"""Retaining walls by limit states (method ``limitStates`` of the pack's
``geotechnicalMethods.retaining``; alpha 9 C5c).

A cantilever wall's service forces (:func:`saengine.substructure.retaining_walls.wall_forces`)
are factored in each combination of the pack's design approach (the sets A, M, R):

- earth pressure: the soil's part of the thrust (and of the surcharge's) times
  Ka(φ'd) / Ka(φ'k), φ'd = atan(tan φ'k / γφ') of the combination's M set, Ka by Rankine on the
  retained soil (K0 = 1 - sin φ' at rest; SAEngine practice for the ratio); the water as it is;
- actions: γG (unfavourable) on the thrust and the water (permanent), γQ on the surcharge's
  thrust; the weights favourable (γG,fav) for sliding, unfavourable or favourable for bearing as
  they act, the surcharge on the heel left out where it helps; the uplift unfavourable;
- sliding: Hd against Rd = V'd tan δd / γR,h (δd = φ'cv,d cast in place, the pack's sliding
  rules; undrained A' cu,d / γR,h) plus the passive resistance (where the wall states it) /
  γR,e;
- bearing: Vd on the effective width B' = B - 2e of the strip (EN 1997-1 Annex D through
  :func:`saengine.substructure.limit_state_geotechnics.bearing_resistance`), the founding
  soil's φ'k, c'k, cu,k at the base;
- overturning: static equilibrium (EQU: γG,dst, γG,stb, γQ,dst of the pack's ``equilibrium``):
  the destabilising moment about the toe at most the stabilising one.

The stem and base are designed with the pack's concrete methods (MRd on the design strengths,
VRd,c) under γG of set A1 on the earth pressure, in place of the parent's load factor on H.
Units: kN/m, kN·m/m, kPa, m.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.design import method_selection
from saengine.substructure import limit_state_geotechnics as lsg


def selected() -> bool:
    return method_selection.geotechnical("retaining") == "limitStates" and lsg.rules() is not None


def cite(key: str = "retaining") -> str:
    return code_context.cite("geotechnicalMethods", key)


def earth_factor() -> float | None:
    """γG of the actions set A1 on the earth pressure (the stem's and base's design), None when
    the pack does not pick this method."""
    if not selected():
        return None
    r = lsg.rules()
    first = r.approaches[r.designApproach][0]
    structural = first.structuralActions or first.actions
    return float(r.actions[structural].permanentUnfavourable)


def _k(phi: float, state: str) -> float:
    s = math.sin(math.radians(phi))
    if state == "active":
        return (1 - s) / (1 + s)
    if state == "passive":
        return (1 + s) / (1 - s)
    return 1 - s


def stability_rows(
    wall: Any,
    s: Any,
    soil: Any,
    forces: list[Any],
    terms: dict[str, Any],
    passive: float,
    state: str,
) -> list[dict[str, Any]]:
    """The sliding, bearing and overturning rows of a cantilever wall per design combination
    (see the module notes)."""
    from saengine.design.check import _check

    r = lsg.rules()
    rules = r.retaining
    depth = s.retained_depth + 0.01
    phi_k = soil.phi(0.01) or 30.0
    base_phi = soil.phi(depth)
    base_c = soil.cohesion(depth)
    base_gamma = soil.total_unit_weight(depth)
    cu_k = base_c if base_phi is None else None
    water = terms.get("water", 0.0) or 0.0
    rows: list[dict[str, Any]] = []
    for k, combo in enumerate(r.approaches[r.designApproach]):
        label = f"{r.designApproach}" + (
            f"-{k + 1}" if len(r.approaches[r.designApproach]) > 1 else ""
        )
        a = r.actions[combo.actions]
        m = r.materials[combo.materials]
        resist = r.spreadResistances[combo.resistances]
        phi_d = math.degrees(math.atan(math.tan(math.radians(phi_k)) / m.tanPhi))
        k_ratio = _k(phi_d, state) / _k(phi_k, state)
        hd = vd_fav = vd_unf = 0.0
        for f in forces:
            h, v = f.h, f.v
            if f.kind == "H":
                h = (h - water) * k_ratio + water
                v *= k_ratio
                hd += a.permanentUnfavourable * h
                vd_fav += a.permanentFavourable * v
                vd_unf += a.permanentUnfavourable * v
            elif f.kind == "L":
                if h:
                    hd += a.variableUnfavourable * h * k_ratio
                else:
                    vd_unf += a.variableUnfavourable * v  # the surcharge on the heel: bearing only
            elif f.kind == "U":
                if v:
                    vd_fav += a.permanentUnfavourable * v
                    vd_unf += a.permanentUnfavourable * v
                hd += a.permanentFavourable * h  # the water in front resists (negative)
            elif f.kind == "D":
                vd_fav += a.permanentFavourable * v
                vd_unf += a.permanentUnfavourable * v
        # Sliding.
        if base_phi is not None:
            delta = math.atan(math.tan(math.radians(base_phi)) / m.tanPhi)
            delta *= 1.0 if rules.castInPlace else r.sliding.precast if r.sliding else 2 / 3
            rd = max(vd_fav, 0.0) * math.tan(delta) / resist.sliding
            how = f"δd = {math.degrees(delta):.1f}° (φ'k = {base_phi:g}° under the base)"
        else:
            rd = s.width * (cu_k or 0.0) / m.undrained / resist.sliding
            how = f"undrained, cu,d = {(cu_k or 0) / m.undrained:.0f} kPa"
        kp_ratio = _k(phi_d, "passive") / _k(phi_k, "passive")
        rd += passive * kp_ratio / resist.earth
        rows.append(
            _check(
                f"Sliding resistance ({label})",
                max(hd, 0.0),
                rd,
                "kN/m",
                label,
                f"sets {combo.actions} + {combo.materials} + {combo.resistances}: Hd with Ka(φ'd) "
                f"/ Ka(φ'k) = {k_ratio:.3f} (φ'd = {phi_d:.1f}°), Rd = V'd tan δd / γR,h, {how}"
                + (
                    f", passive / γR,e = {passive * kp_ratio / resist.earth:.1f} kN/m"
                    if passive
                    else ""
                )
                + f" ({cite()})",
            )
        )
        # Bearing on the effective width.
        n = vd_unf
        if n > 0:
            moment = 0.0
            for f in forces:
                factor = a.permanentUnfavourable
                if f.kind == "L":
                    factor = a.variableUnfavourable
                h = f.h * (k_ratio if f.kind in ("H", "L") else 1.0)
                moment += factor * (f.v * f.x - h * f.y)
            x = moment / n
            e = s.width / 2 - x
            params = lsg.design_parameters(base_phi or 0.0, 0.0 if cu_k else base_c,
                                           cu_k, base_gamma, combo.materials)  # fmt: skip
            front = soil.below(s.front_offset)
            q = front.sigma_v_eff(max(s.retained_depth - s.front_offset, 0.0))
            length = 1000.0
            res = lsg.bearing_resistance(
                s.width, length, params, q, None, n * length, max(hd, 0.0) * length, abs(e), 0.0,
                0.0, base_phi is not None,
            )  # fmt: skip
            rd_b = lsg.bearing_design(res["R"], combo.resistances) / length
            rows.append(
                _check(
                    f"Bearing resistance ({label})",
                    n,
                    rd_b,
                    "kN/m",
                    label,
                    f"B' = B - 2e = {max(s.width - 2 * abs(e), 0.0):.2f} m (e = {e:.2f} m), R/A' = "
                    f"{res['q']:.0f} kPa, q' = {q:.0f} kPa; "
                    + (
                        f"φ'k = {base_phi:g}°"
                        if base_phi is not None
                        else f"cu,k = {cu_k or 0:g} kPa"
                    )
                    + f" ({cite('bearing')})",
                )
            )
    # Overturning (EQU).
    eq = r.equilibrium
    if eq is not None:
        dst = stb = 0.0
        for f in forces:
            if f.kind == "L" and not f.h:
                continue  # the surcharge on the heel helps: left out
            over = max(f.h * f.y, 0.0) + max(-f.v * f.x, 0.0)
            hold = max(f.v * f.x, 0.0) + max(-f.h * f.y, 0.0)
            variable = f.kind == "L"
            dst += over * (eq.variableDestabilising if variable else eq.permanentDestabilising)
            stb += hold * eq.permanentStabilising
        rows.append(
            _check(
                "Overturning (EQU)",
                dst,
                stb,
                "kN·m/m",
                "EQU",
                f"about the toe: Edst,d with γG,dst = {eq.permanentDestabilising:g}, γQ,dst = "
                f"{eq.variableDestabilising:g}; Estb,d with γG,stb = {eq.permanentStabilising:g} "
                f"({cite('equilibrium')})",
            )
        )
    return rows

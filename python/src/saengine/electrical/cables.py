"""Cable sizing, ampacity derating and voltage drop (IEC 60364-5-52, IEC 60364-4-43).

All tables (ampacity ``It``, correction factors ``Ca``, ``Cg``, ``Ci``, resistance/reactance
per km, ``mV/A/m``, voltage-drop limits and adiabatic ``k``) are read from the active code pack's
``electrical`` table (:mod:`saengine.electrical.tables`).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from saengine.electrical import tables as T


def size_key(size: float) -> str:
    """Canonical dictionary key for a conductor cross-section [mm²]."""
    value = float(size)
    return str(int(value)) if value.is_integer() else f"{value:g}"


def lookup_step(table: dict[str, Any], target: float, mode: str = "ceil") -> float:
    """Lookup a numeric-keyed pack dictionary conservatively (exact match, else next key up)."""
    pairs = sorted((float(k), float(v)) for k, v in table.items())
    if not pairs:
        raise ValueError("empty lookup table in electrical code pack")
    if mode == "ceil":
        for key, val in pairs:
            if key >= target - 1e-9:
                return val
        return pairs[-1][1]
    for key, val in reversed(pairs):
        if key <= target + 1e-9:
            return val
    return pairs[0][1]


def lookup_ampacity(
    size: float,
    conductor: str = "Cu",
    insulation: str = "PVC",
    method: str = "C",
    phases: int = 1,
) -> float | None:
    """Base current-carrying capacity ``It`` [A] at the pack's reference ambient temperature."""
    cables = T.cables()
    cores = "2" if phases == 1 else "3"
    by_cond = cables.ampacity.get(conductor) or {}
    by_ins = by_cond.get(insulation) or {}
    by_method = by_ins.get(method) or {}
    by_cores = by_method.get(cores) or {}
    val = by_cores.get(size_key(size))
    return float(val) if val is not None else None


def correction_factors(
    insulation: str = "PVC",
    ambient_temp: float | None = None,
    grouped_circuits: int = 1,
    grouping_arrangement: str = "bunched",
    thermal_insulation: str = "none",
) -> dict[str, float]:
    """Correction factors ``Ca`` (ambient), ``Cg`` (grouping) and ``Ci`` (thermal insulation)."""
    cables = T.cables()
    rules = T.circuit_rules()
    temp = float(rules.defaultAmbientTemp if ambient_temp is None else ambient_temp)
    ca_table = cables.ambientFactor.get(insulation)
    if not ca_table:
        raise ValueError(f"no ambient temperature factors for insulation '{insulation}'")
    ca = lookup_step(ca_table, temp, mode="ceil")
    cg_table = cables.groupingFactor.get(grouping_arrangement)
    if not cg_table:
        raise ValueError(f"no grouping factors for arrangement '{grouping_arrangement}'")
    cg = lookup_step(cg_table, float(max(1, grouped_circuits)), mode="ceil")
    ci = float(cables.thermalInsulationFactor.get(thermal_insulation, 1.0))
    return {
        "ambientTemp": temp,
        "Ca": ca,
        "Cg": cg,
        "Ci": ci,
        "factor": ca * cg * ci,
    }


def effective_ampacity(
    size: float,
    conductor: str = "Cu",
    insulation: str = "PVC",
    method: str = "C",
    phases: int = 1,
    ambient_temp: float | None = None,
    grouped_circuits: int = 1,
    grouping_arrangement: str = "bunched",
    thermal_insulation: str = "none",
) -> dict[str, Any]:
    """Effective current-carrying capacity ``Iz = It * Ca * Cg * Ci`` [A]."""
    it = lookup_ampacity(size, conductor, insulation, method, phases)
    factors = correction_factors(
        insulation=insulation,
        ambient_temp=ambient_temp,
        grouped_circuits=grouped_circuits,
        grouping_arrangement=grouping_arrangement,
        thermal_insulation=thermal_insulation,
    )
    iz = it * factors["factor"] if it is not None else None
    return {
        "size": float(size),
        "It": it,
        **factors,
        "Iz": iz,
    }


def standard_breaker(ib: float, ratings: Sequence[float] | None = None) -> float | None:
    """Smallest standard protective device nominal rating ``In >= Ib`` [A]."""
    pool = list(ratings) if ratings is not None else list(T.circuit_rules().breakerRatings)
    return T.next_size(ib, pool)


def default_cpc_size(phase_size: float) -> float:
    """Protective conductor size [mm²] per IEC 60364-5-54 Table 54.2 (Cu same material)."""
    sizes = sorted(float(s) for s in T.cables().sizes)
    s = float(phase_size)
    if s <= 16.0 + 1e-9:
        return s
    if s <= 35.0 + 1e-9:
        return 16.0
    return T.next_size(s / 2.0, sizes) or sizes[-1]


def voltage_drop_limit(kind: str = "power") -> float:
    """Maximum cumulative voltage drop [%] from the pack (3 % lighting / 5 % other)."""
    limits = T.cables().voltageDropLimits
    return float(limits["lighting"] if kind == "lighting" else limits["other"])


def voltage_drop(
    size: float,
    ib: float,
    length_m: float,
    phases: int = 1,
    pf: float = 1.0,
    conductor: str = "Cu",
    insulation: str = "PVC",
    mode: str = "mv_a_m",
    voltage: float | None = None,
) -> dict[str, Any]:
    """Voltage drop of a single cable run by ``mV/A/m`` or ``R/X`` with ``cos phi``.

    ``mode='mv_a_m'``: ``Vd = mV/A/m * Ib * L / 1000``.
    ``mode='rx'``: ``Vd = k_ph * Ib * L * (R_op * cos(phi) + X * sin(phi)) / 1000``,
    where ``k_ph`` is ``2`` (single-phase) or ``sqrt(3)`` (three-phase).
    """
    cables = T.cables()
    rules = T.circuit_rules()
    v_ref = float(
        voltage if voltage is not None else (rules.phaseVoltage if phases == 1 else T.LT_VOLTAGE)
    )
    key = size_key(size)
    ph_key = "1ph" if phases == 1 else "3ph"
    mv_table = ((cables.mvAm.get(conductor) or {}).get(insulation) or {}).get(ph_key) or {}
    mv_val = mv_table.get(key)
    imp = (cables.impedance.get(conductor) or {}).get(key)
    temp_factor = float(cables.conductorTempFactor.get(insulation, 1.2))
    r_op = float(imp.r20) * temp_factor if imp is not None else None
    x_val = float(imp.x) if imp is not None else None

    if mode == "rx" and r_op is not None and x_val is not None:
        k_ph = 2.0 if phases == 1 else math.sqrt(3)
        sin_phi = math.sqrt(max(0.0, 1.0 - pf * pf))
        eff_mv_a_m = k_ph * (r_op * pf + x_val * sin_phi)
        used_mode = "rx"
    elif mv_val is not None:
        eff_mv_a_m = float(mv_val)
        used_mode = "mv_a_m"
    elif r_op is not None and x_val is not None:
        k_ph = 2.0 if phases == 1 else math.sqrt(3)
        sin_phi = math.sqrt(max(0.0, 1.0 - pf * pf))
        eff_mv_a_m = k_ph * (r_op * pf + x_val * sin_phi)
        used_mode = "rx"
    else:
        raise ValueError(f"no voltage-drop data for {size:g} mm² {conductor} {insulation}")

    vd_v = eff_mv_a_m * ib * length_m / 1000.0
    vd_pct = (vd_v / v_ref * 100.0) if v_ref > 0 else 0.0
    return {
        "size": float(size),
        "vdV": vd_v,
        "vdPct": vd_pct,
        "mvPerAM": eff_mv_a_m,
        "rOp": r_op,
        "x": x_val,
        "voltage": v_ref,
        "mode": used_mode,
    }


def adiabatic_min_size(
    ik_ka: float,
    duration_s: float,
    conductor: str = "Cu",
    insulation: str = "PVC",
    i2t: float | None = None,
) -> float:
    """Minimum conductor cross-section ``S >= sqrt(I^2 * t) / k`` [mm²] (IEC 60364-4-43)."""
    cables = T.cables()
    k = float((cables.adiabaticK.get(conductor) or {})[insulation])
    energy = float(i2t) if i2t is not None else (ik_ka * 1000.0) ** 2 * duration_s
    return math.sqrt(max(0.0, energy)) / k


def _evaluate_size(
    size: float,
    ib: float,
    in_rating: float,
    length_m: float,
    phases: int,
    pf: float,
    conductor: str,
    insulation: str,
    method: str,
    ambient_temp: float | None,
    grouped_circuits: int,
    grouping_arrangement: str,
    thermal_insulation: str,
    upstream_vd_pct: float,
    vd_limit_pct: float,
    vd_mode: str,
    min_adiabatic_s: float,
    voltage: float | None,
) -> dict[str, Any] | None:
    amp = effective_ampacity(
        size,
        conductor=conductor,
        insulation=insulation,
        method=method,
        phases=phases,
        ambient_temp=ambient_temp,
        grouped_circuits=grouped_circuits,
        grouping_arrangement=grouping_arrangement,
        thermal_insulation=thermal_insulation,
    )
    if amp["It"] is None or amp["Iz"] is None:
        return None
    vd = voltage_drop(
        size,
        ib=ib,
        length_m=length_m,
        phases=phases,
        pf=pf,
        conductor=conductor,
        insulation=insulation,
        mode=vd_mode,
        voltage=voltage,
    )
    cum_vd = upstream_vd_pct + vd["vdPct"]
    amp_ok = ib <= in_rating + 1e-9 and in_rating <= amp["Iz"] + 1e-9
    vd_ok = cum_vd <= vd_limit_pct + 1e-9
    fault_ok = size >= min_adiabatic_s - 1e-9
    return {
        **amp,
        **vd,
        "Ib": ib,
        "In": in_rating,
        "upstreamVdPct": upstream_vd_pct,
        "cumVdPct": cum_vd,
        "vdLimitPct": vd_limit_pct,
        "minAdiabaticMm2": min_adiabatic_s,
        "ampacityOk": amp_ok,
        "vdOk": vd_ok,
        "faultOk": fault_ok,
        "ok": amp_ok and vd_ok and fault_ok,
    }


def size_cable(
    ib: float,
    length_m: float,
    *,
    phases: int = 1,
    pf: float = 0.85,
    kind: str = "power",
    conductor: str | None = None,
    insulation: str | None = None,
    method: str | None = None,
    ambient_temp: float | None = None,
    grouped_circuits: int = 1,
    grouping_arrangement: str = "bunched",
    thermal_insulation: str = "none",
    in_rating: float | None = None,
    upstream_vd_pct: float = 0.0,
    vd_limit_pct: float | None = None,
    vd_mode: str = "mv_a_m",
    ik_ka: float | None = None,
    fault_duration_s: float | None = None,
    i2t: float | None = None,
    min_size: float | None = None,
    specified_size: float | None = None,
    voltage: float | None = None,
) -> dict[str, Any]:
    """Select the smallest standard cable satisfying ``Ib <= In <= Iz``, cumulative voltage drop,
    and adiabatic fault withstand ``k^2 S^2 >= I^2 t``.

    When ``specified_size`` is supplied, evaluates that size and reports ``recommendedSize``
    (the smallest size that passes all checks) if ``specified_size`` fails or differs.
    """
    cables = T.cables()
    rules = T.circuit_rules()
    cond = conductor or rules.defaultConductor
    ins = insulation or rules.defaultFinalInsulation
    meth = method or rules.defaultMethod
    rating = float(in_rating) if in_rating is not None else standard_breaker(ib)
    if rating is None:
        raise ValueError(f"design current {ib:.1f} A exceeds largest standard breaker rating")
    limit_pct = float(vd_limit_pct if vd_limit_pct is not None else voltage_drop_limit(kind))
    min_s = float(min_size or 0.0)
    if kind in rules.circuitDefaults and min_size is None:
        min_s = float(rules.circuitDefaults[kind].minCableMm2)

    min_adiabatic = 0.0
    if i2t is not None or (ik_ka is not None and ik_ka > 0 and fault_duration_s is not None):
        min_adiabatic = adiabatic_min_size(
            float(ik_ka or 0.0), float(fault_duration_s or 0.0), cond, ins, i2t=i2t
        )

    candidates = [float(s) for s in sorted(cables.sizes) if float(s) >= min_s - 1e-9]
    recommended: dict[str, Any] | None = None
    last_eval: dict[str, Any] | None = None
    for s in candidates:
        ev = _evaluate_size(
            s,
            ib,
            rating,
            length_m,
            phases,
            pf,
            cond,
            ins,
            meth,
            ambient_temp,
            grouped_circuits,
            grouping_arrangement,
            thermal_insulation,
            upstream_vd_pct,
            limit_pct,
            vd_mode,
            min_adiabatic,
            voltage,
        )
        if ev is None:
            continue
        last_eval = ev
        if ev["ok"]:
            recommended = ev
            break

    if specified_size is not None:
        chosen = _evaluate_size(
            float(specified_size),
            ib,
            rating,
            length_m,
            phases,
            pf,
            cond,
            ins,
            meth,
            ambient_temp,
            grouped_circuits,
            grouping_arrangement,
            thermal_insulation,
            upstream_vd_pct,
            limit_pct,
            vd_mode,
            min_adiabatic,
            voltage,
        )
        if chosen is None:
            raise ValueError(
                f"no ampacity data for {specified_size:g} mm² {cond} {ins} method {meth}"
            )
    else:
        chosen = recommended or last_eval
        if chosen is None:
            raise ValueError(f"no standard cable sizes for {cond} {ins} method {meth}")

    reasons: list[str] = []
    if not chosen["ampacityOk"]:
        reasons.append(f"In {rating:g} A > Iz {chosen['Iz']:.1f} A")
    if not chosen["vdOk"]:
        reasons.append(f"cumulative Vd {chosen['cumVdPct']:.2f}% > {limit_pct:g}%")
    if not chosen["faultOk"]:
        reasons.append(f"cable {chosen['size']:g} mm² < adiabatic minimum {min_adiabatic:.2f} mm²")
    chosen["recommendedSize"] = recommended["size"] if recommended else None
    chosen["conductor"] = cond
    chosen["insulation"] = ins
    chosen["method"] = meth
    chosen["note"] = "; ".join(reasons)
    return chosen

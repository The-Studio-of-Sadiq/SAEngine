"""Simplified short-circuit and fault-loop checks (IEC 60909-0, IEC 60364-4-41).

Computes prospective ``Ik3 max`` (three-phase symmetrical) and ``Ik1 min`` (single-phase
line-to-earth at operating/hot conductor temperature) at the transformer LV terminals, at each
distribution board, and at the end of each final circuit; checks breaking capacity ``Icu >= Ik3``
and earth-fault loop disconnection ``Zs <= limit``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from saengine.electrical import tables as T
from saengine.electrical.cables import default_cpc_size, lookup_step, size_key

_UNSET = object()


def transformer_source(
    kva: float,
    voltage_v: float | None = None,
    uk_pct: float | None = None,
    xr_ratio: float | None = None,
    grid_sk_mva: Any = _UNSET,
    c_max: float | None = None,
    c_min: float | None = None,
    parallel: int = 1,
) -> dict[str, Any]:
    """Source impedance and prospective short-circuit currents at the LV terminals (IEC 60909-0).

    ``Z_T = (uk / 100) * U_rT^2 / S_rT`` (divided by ``parallel`` when identical transformers run
    in parallel), optionally combined with HV grid impedance ``Z_Q = c_max * U_n^2 / S_kQ``.
    ``Ik3 = c_max * U_n / (sqrt(3) * Z_k)``.
    """
    if kva <= 0:
        raise ValueError("transformer kVA must be positive")
    sc = T.short_circuit()
    u_n = float(voltage_v if voltage_v is not None else T.LT_VOLTAGE)
    uk = float(uk_pct if uk_pct is not None else lookup_step(sc.transformerUk, kva, mode="ceil"))
    xr = float(
        xr_ratio if xr_ratio is not None else lookup_step(sc.transformerXr, kva, mode="ceil")
    )
    cmax = float(sc.cMax if c_max is None else c_max)
    cmin = float(sc.cMin if c_min is None else c_min)
    n = max(1, int(parallel))

    z_tx_one = (uk / 100.0) * (u_n**2) / (kva * 1000.0)
    r_tx_one = z_tx_one / math.sqrt(1.0 + xr**2)
    x_tx_one = r_tx_one * xr
    r_tx = r_tx_one / n
    x_tx = x_tx_one / n

    sk = sc.gridSkMva if grid_sk_mva is _UNSET else grid_sk_mva
    if sk is not None and float(sk) > 0:
        z_q = cmax * (u_n**2) / (float(sk) * 1e6)
        rx = float(sc.gridRxRatio)
        x_q = z_q / math.sqrt(1.0 + rx**2)
        r_q = x_q * rx
    else:
        sk = None
        r_q = x_q = 0.0

    r_tot = r_tx + r_q
    x_tot = x_tx + x_q
    z_tot = math.hypot(r_tot, x_tot)
    ik3_ka = cmax * u_n / (math.sqrt(3) * z_tot) / 1000.0
    u0 = u_n / math.sqrt(3)
    ik1_ka = cmin * u0 / z_tot / 1000.0
    return {
        "kva": float(kva),
        "parallel": n,
        "voltageV": u_n,
        "u0V": u0,
        "ukPct": uk,
        "xrRatio": xr,
        "cMax": cmax,
        "cMin": cmin,
        "gridSkMva": float(sk) if sk is not None else None,
        "rTx": r_tx,
        "xTx": x_tx,
        "rGrid": r_q,
        "xGrid": x_q,
        "rTotal": r_tot,
        "xTotal": x_tot,
        "zTotal": z_tot,
        "ik3Ka": ik3_ka,
        "ik1Ka": ik1_ka,
    }


def _r20_of(conductor: str, size: float) -> tuple[float, float]:
    cables = T.cables()
    table = cables.impedance.get(conductor) or {}
    row = table.get(size_key(size))
    if row is not None:
        return float(row.r20), float(row.x)
    # Fall back by scaling from the smallest tabulated size of the same conductor.
    pairs = sorted((float(k), v) for k, v in table.items())
    if not pairs:
        raise ValueError(f"no impedance table for conductor '{conductor}'")
    ref_s, ref_row = pairs[0]
    return float(ref_row.r20) * (ref_s / float(size)), float(ref_row.x)


def cable_segment_impedance(
    size: float,
    length_m: float,
    conductor: str = "Cu",
    insulation: str = "PVC",
    cpc_size: float | None = None,
    hot: bool = False,
) -> dict[str, float]:
    """Phase and protective-conductor impedance [ohm] of a cable run of ``length_m`` [m]."""
    cables = T.cables()
    factor = float(cables.conductorTempFactor.get(insulation, 1.2)) if hot else 1.0
    r20_ph, x_ph_km = _r20_of(conductor, size)
    cpc = float(cpc_size) if cpc_size is not None else default_cpc_size(size)
    r20_pe, x_pe_km = _r20_of(conductor, cpc)
    km = float(length_m) / 1000.0
    return {
        "rPh": r20_ph * factor * km,
        "xPh": x_ph_km * km,
        "rPe": r20_pe * factor * km,
        "xPe": x_pe_km * km,
    }


def busbar_segment_impedance(rating: float, length_m: float) -> dict[str, float]:
    """Busbar trunking segment impedance [ohm] from the pack's typical mOhm/m table."""
    sc = T.short_circuit()
    if not sc.busbarImpedancePerM:
        return {"rPh": 0.0, "xPh": 0.0, "rPe": 0.0, "xPe": 0.0}
    pairs = sorted((float(k), v) for k, v in sc.busbarImpedancePerM.items())
    chosen = next((v for k, v in pairs if k >= rating - 1e-9), pairs[-1][1])
    r_mohm_m, x_mohm_m = float(chosen[0]), float(chosen[1])
    r = r_mohm_m * float(length_m) / 1000.0
    x = x_mohm_m * float(length_m) / 1000.0
    return {"rPh": r, "xPh": x, "rPe": r, "xPe": x}


def fault_at_node(source: dict[str, Any], segments: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Prospective ``Ik3 max``, ``Ik1 min`` [kA] and loop impedance ``Zs`` [ohm] downstream of
    ``segments``.

    Each segment dict is either ``{"kind": "busbar", "rating": ..., "length": ...}`` or a cable
    segment ``{"size": ..., "length": ..., "conductor": ..., "insulation": ..., "cpcSize": ...}``.
    """
    r_cold = float(source["rTotal"])
    x_cold = float(source["xTotal"])
    r_loop = float(source["rTotal"])
    x_loop = float(source["xTotal"])

    for seg in segments:
        if seg.get("kind") == "busbar":
            zc = busbar_segment_impedance(float(seg.get("rating") or 400.0), float(seg["length"]))
            zh = zc
        else:
            size = float(seg["size"])
            length = float(seg["length"])
            cond = str(seg.get("conductor") or "Cu")
            ins = str(seg.get("insulation") or "PVC")
            cpc = seg.get("cpcSize")
            zc = cable_segment_impedance(size, length, cond, ins, cpc, hot=False)
            zh = cable_segment_impedance(size, length, cond, ins, cpc, hot=True)
        r_cold += zc["rPh"]
        x_cold += zc["xPh"]
        r_loop += zh["rPh"] + zh["rPe"]
        x_loop += zh["xPh"]

    z_max = math.hypot(r_cold, x_cold)
    z_s = math.hypot(r_loop, x_loop)
    u_n = float(source["voltageV"])
    u0 = float(source["u0V"])
    cmax = float(source["cMax"])
    cmin = float(source["cMin"])
    ik3_max = cmax * u_n / (math.sqrt(3) * z_max) / 1000.0
    ik1_min = cmin * u0 / z_s / 1000.0
    return {
        "r3ph": r_cold,
        "x3ph": x_cold,
        "z3ph": z_max,
        "zsOhm": z_s,
        "ik3MaxKa": ik3_max,
        "ik1MinKa": ik1_min,
    }


def zs_limit(in_rating: float, curve: str = "C", voltage_0: float | None = None) -> float:
    """Maximum earth-fault loop impedance ``Zs`` [ohm] for instantaneous disconnection
    (IEC 60364-4-41 / IEC 60898-1): ``Zs_max = U0 * Cmin / (m * In)``."""
    sc = T.short_circuit()
    rules = T.circuit_rules()
    u0 = float(voltage_0 if voltage_0 is not None else rules.phaseVoltage)
    m = float(sc.mcbTripMultiplier.get(curve, sc.mcbTripMultiplier.get("C", 10.0)))
    return u0 * float(sc.zsCmin) / (m * float(in_rating))


def check_disconnection(
    zs_ohm: float,
    in_rating: float,
    curve: str = "C",
    voltage_0: float | None = None,
) -> dict[str, Any]:
    """Check ``Zs <= Zs_max`` for the protective device curve and rating."""
    sc = T.short_circuit()
    rules = T.circuit_rules()
    u0 = float(voltage_0 if voltage_0 is not None else rules.phaseVoltage)
    m = float(sc.mcbTripMultiplier.get(curve, sc.mcbTripMultiplier.get("C", 10.0)))
    limit = zs_limit(in_rating, curve=curve, voltage_0=u0)
    ia_min = m * float(in_rating)
    ik1_a = float(sc.zsCmin) * u0 / zs_ohm if zs_ohm > 0 else math.inf
    ok = zs_ohm <= limit + 1e-9
    note = (
        ""
        if ok
        else f"Zs {zs_ohm:.3f} ohm > limit {limit:.3f} ohm ({curve}{in_rating:g}, Ia = {ia_min:g} A)"
    )
    return {
        "zsOhm": zs_ohm,
        "zsMaxOhm": limit,
        "ik1MinA": ik1_a,
        "iaMinA": ia_min,
        "ok": ok,
        "note": note,
    }


def select_breaking_capacity(
    ik3_max_ka: float,
    device_type: str = "MCB",
) -> float:
    """Smallest standard breaking capacity ``Icu >= max(default, Ik3 max)`` [kA]."""
    rules = T.circuit_rules()
    minimum = float(rules.breakingCapacityKa.get(device_type, 6.0))
    need = max(minimum, float(ik3_max_ka))
    pool = list(rules.standardBreakingCapacitiesKa)
    return float(T.next_size(need, pool) or max(pool, default=need))


def check_breaking_capacity(
    ik3_max_ka: float,
    device_type: str = "MCB",
    breaking_capacity_ka: float | None = None,
) -> dict[str, Any]:
    """Check protective device breaking capacity ``Icu >= Ik3 max``."""
    rules = T.circuit_rules()
    icu = float(
        breaking_capacity_ka
        if breaking_capacity_ka is not None
        else rules.breakingCapacityKa.get(device_type, 6.0)
    )
    ok = ik3_max_ka <= icu + 1e-9
    note = "" if ok else f"Ik3 {ik3_max_ka:.2f} kA > {device_type} Icu {icu:g} kA"
    return {
        "ik3MaxKa": ik3_max_ka,
        "icuKa": icu,
        "ok": ok,
        "note": note,
    }

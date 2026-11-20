"""Domestic hot water heater sizing and recirculation loop hydraulics.

Heater storage + recovery sizing follows ASHRAE HVAC Applications Ch. 50 / CIBSE Guide G
storage-recovery balance, and recirculation flow + pipe sizing reuses
:mod:`saengine.plumbing.supply` and :mod:`saengine.plumbing.hydraulics`. All design parameters
come from the code pack's ``plumbing.hotWater`` table (:mod:`saengine.plumbing.tables`).
"""

from __future__ import annotations

from typing import Any

from saengine.mep import code_pack
from saengine.plumbing import tables as T
from saengine.plumbing.demand import hunter_flow, supply_units
from saengine.plumbing.hydraulics import fitting_length, hazen_williams_loss
from saengine.plumbing.supply import size_pipe


def _hw_table() -> Any:
    table = T.HOT_WATER
    if table is None:
        raise ValueError(code_pack.not_covered("Hot water system sizing"))
    return table


def _occupancy_family(occupancy: str | None) -> str:
    if not occupancy:
        return "default"
    low = occupancy.lower()
    if "hotel" in low:
        return "hotel"
    if "hospital" in low or "medical" in low:
        return "hospital"
    if "school" in low or "college" in low:
        return "school"
    if "office" in low:
        return "office"
    if "family" in low or "apartment" in low or "flat" in low or "residen" in low or "dorm" in low:
        return "residential"
    return "default"


def fixture_peak_demand(fixtures: Any, occupancy: str | None = None) -> tuple[float, float, float]:
    """(possible_lph, demand_factor, peak_lph) from fixture counts."""
    table = _hw_table()
    possible = 0.0
    for key, rate in table.fixtureDemandLph.items():
        count = fixtures.get(key, 0) if isinstance(fixtures, dict) else getattr(fixtures, key, 0)
        if count:
            possible += float(count) * float(rate)
    family = _occupancy_family(occupancy)
    factor = float(table.demandFactor.get(family, table.demandFactor["default"]))
    return possible, factor, possible * factor


def heater_sizing(
    demand: Any,
    *,
    occupancy: str | None = None,
    cold_temp_c: float | None = None,
    storage_temp_c: float | None = None,
    peak_hours: float | None = None,
    usable_fraction: float | None = None,
    demand_factor: float | None = None,
    storage_factor: float | None = None,
    storage_volume_l: float | None = None,
    recovery_rate_lph: float | None = None,
) -> dict[str, Any]:
    """Size hot water storage volume [L] and recovery heating power [kW].

    ``demand`` may be a fixture object/dict (converted via fixture demand and demand factor)
    or a direct peak hourly demand [L/h].
    """
    table = _hw_table()
    if isinstance(demand, int | float):
        possible = float(demand)
        df = 1.0 if demand_factor is None else float(demand_factor)
        peak = possible * df
    else:
        possible, default_df, _ = fixture_peak_demand(demand, occupancy)
        df = default_df if demand_factor is None else float(demand_factor)
        peak = possible * df

    t_cold = float(cold_temp_c if cold_temp_c is not None else table.coldTempC)
    t_store = float(storage_temp_c if storage_temp_c is not None else table.storageTempC)
    delta_t = max(t_store - t_cold, 0.0)
    t_p = float(peak_hours if peak_hours is not None else table.peakHours)
    uf = float(usable_fraction if usable_fraction is not None else table.usableFraction)
    family = _occupancy_family(occupancy)
    sf = float(
        storage_factor
        if storage_factor is not None
        else table.storageFactor.get(family, table.storageFactor["default"])
    )

    if storage_volume_l is not None:
        storage = float(storage_volume_l)
        recovery = max(0.0, peak - (storage * uf) / t_p)
    elif recovery_rate_lph is not None:
        recovery = float(recovery_rate_lph)
        storage = max(0.0, (peak - recovery) * t_p / uf)
    else:
        recovery = (peak * t_p) / (t_p + sf * uf) if (t_p + sf * uf) > 0 else peak
        storage = sf * recovery

    cp = float(table.specificHeatKjKgK)
    power_kw = (recovery / 3600.0) * cp * delta_t
    stored_kwh = (storage * uf / 3600.0) * cp * delta_t
    return {
        "possibleDemandLph": round(possible, 1),
        "demandFactor": round(df, 3),
        "peakDemandLph": round(peak, 1),
        "storageVolumeL": round(storage, 1),
        "usableVolumeL": round(storage * uf, 1),
        "recoveryRateLph": round(recovery, 1),
        "coldTempC": t_cold,
        "storageTempC": t_store,
        "deltaTK": round(delta_t, 1),
        "powerKw": round(power_kw, 2),
        "storedKwh": round(stored_kwh, 2),
        "peakHours": t_p,
        "usableFraction": uf,
    }


def recirculation_loop(
    loop_length_m: float,
    *,
    heat_loss_w_per_m: float | None = None,
    return_drop_c: float | None = None,
    material: str | None = None,
) -> dict[str, Any]:
    """Compute recirculation flow [L/min] for allowable temperature drop and size the return pipe."""
    table = _hw_table()
    loss_rate = float(heat_loss_w_per_m if heat_loss_w_per_m is not None else table.heatLossWPerM)
    drop_k = float(return_drop_c if return_drop_c is not None else table.returnDropC)
    cp = float(table.specificHeatKjKgK)
    heat_loss_w = max(loop_length_m, 0.0) * loss_rate
    flow_lps = (heat_loss_w / 1000.0) / (cp * drop_k) if drop_k > 0 else 0.0
    flow_lpm = flow_lps * 60.0
    mat = material or "PPR"
    sized = size_pipe(flow_lpm, mat, minimum=13)
    dia = sized["diameter"] or 13
    c = T.HAZEN_C.get(mat, 150)
    eq_len = fitting_length(dia, {"elbow": 6, "teeRun": 4, "check": 1, "gate": 2})
    head_loss_m = hazen_williams_loss(
        flow_lpm / 60000.0, dia / 1000.0, max(loop_length_m, 0.1) + eq_len, c
    )
    return {
        "loopLengthM": round(loop_length_m, 1),
        "heatLossWPerM": loss_rate,
        "heatLossW": round(heat_loss_w, 1),
        "returnDropK": drop_k,
        "flowLpm": round(flow_lpm, 2),
        "material": mat,
        "pipeDiameterMm": dia,
        "velocityMs": round(sized["velocity"], 3),
        "headLossMPer100M": round(sized["headLoss"], 2),
        "pumpHeadM": round(head_loss_m, 2),
    }


def hot_water_results(mep: Any, building: Any = None) -> dict[str, Any] | None:
    """Hot water heater, supply header and recirculation summary for ``plumbing_results``."""
    plumbing = getattr(mep, "plumbing", None)
    if plumbing is None:
        return None
    hw = getattr(plumbing, "hotWater", None)
    has_hw_riser = any(r.system == "hotWater" for r in plumbing.risers)
    if hw is None and not has_hw_riser:
        return None
    if hw is not None and not hw.enabled:
        return None
    if T.HOT_WATER is None:
        return None

    valves = plumbing.supply.flushValves
    total_possible = 0.0
    total_peak = 0.0
    hot_units = 0.0
    for entry in plumbing.stories:
        poss, _, peak = fixture_peak_demand(entry.fixtures, entry.occupancy)
        total_possible += poss
        total_peak += peak
        u, _, _ = supply_units(entry.fixtures, "hot", valves)
        hot_units += u

    occ = plumbing.stories[0].occupancy if plumbing.stories else None
    sizing = heater_sizing(
        total_peak,
        occupancy=occ,
        cold_temp_c=hw.coldTempC if hw else None,
        storage_temp_c=hw.storageTempC if hw else None,
        peak_hours=hw.peakHours if hw else None,
        usable_fraction=hw.usableFraction if hw else None,
        demand_factor=1.0,
        storage_volume_l=hw.storageVolumeL if hw else None,
        recovery_rate_lph=hw.recoveryRateLph if hw else None,
    )
    sizing["possibleDemandLph"] = round(total_possible, 1)

    # Supply header using plumbing hydraulics
    supply_flow_lpm = hunter_flow(hot_units, valves)
    mat = (hw.material if hw and hw.material else None) or "PPR"
    supply_pipe = size_pipe(supply_flow_lpm, mat, minimum=19)

    # Recirculation loop length estimate from risers if not given
    if hw and hw.loopLengthM is not None:
        loop_m = hw.loopLengthM
    else:
        riser_h = 0.0
        for r in plumbing.risers:
            if (
                r.system == "hotWater"
                and building is not None
                and building.known
                and r.fromStory in building.stories
                and r.toStory in building.stories
            ):
                riser_h += abs(building.stories[r.toStory] - building.stories[r.fromStory]) / 1000.0
        loop_m = max(2.0 * riser_h + 20.0, 20.0) if (riser_h > 0 or total_peak > 0) else 0.0

    recirc = recirculation_loop(
        loop_m,
        heat_loss_w_per_m=hw.heatLossWPerM if hw else None,
        return_drop_c=hw.returnDropC if hw else None,
        material=mat,
    )
    return {
        "hotUnits": round(hot_units, 1),
        "supplyFlowLpm": round(supply_flow_lpm, 1),
        "supplyPipeMm": supply_pipe["diameter"],
        "heater": sizing,
        "recirculation": recirc,
    }

"""Fuel gas (natural gas / LPG) and medical gas piping sizing.

- Fuel gas: appliance demand with diversity, low-pressure Pole's formula from the code pack
  (Q = C * sqrt(dP_mbar * d_mm^5 / (S * L_m))), velocity check and meter/regulator checks.
- Medical gas (O2, N2O, MA4, MA7, VAC, AGSS): outlets per clinical room type, diversified flows,
  copper pipe sizing by velocity limit and allowable pressure drop.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.mep import code_pack
from saengine.mep.routing import path_length
from saengine.plumbing import tables as T


def _gas_table() -> Any:
    table = T.GAS
    if table is None:
        raise ValueError(code_pack.not_covered("Fuel gas piping"))
    return table


def _medgas_table() -> Any:
    table = T.MEDICAL_GAS
    if table is None:
        raise ValueError(code_pack.not_covered("Medical gas piping"))
    return table


def diversity_factor(count: int, steps: list[Any]) -> float:
    """Diversity factor for ``count`` appliances or outlets from a step table."""
    if count <= 0:
        return 0.0
    for row in steps:
        if row.upTo is None or count <= row.upTo:
            return float(row.factor)
    return float(steps[-1].factor)


def pole_flow_m3h(
    drop_kpa: float,
    bore_mm: float,
    sg: float,
    length_m: float,
    pole_constant: float | None = None,
) -> float:
    """Low-pressure Pole's formula: Q [m³/h] = C * sqrt(dP_mbar * d_mm^5 / (S * L_m))."""
    table = _gas_table()
    c = float(pole_constant if pole_constant is not None else table.poleConstant)
    dp_mbar = drop_kpa * 10.0
    if dp_mbar <= 0 or bore_mm <= 0 or sg <= 0 or length_m <= 0:
        return 0.0
    return c * math.sqrt((dp_mbar * (bore_mm**5)) / (sg * length_m))


def pole_drop_kpa(
    flow_m3h: float,
    bore_mm: float,
    sg: float,
    length_m: float,
    pole_constant: float | None = None,
) -> float:
    """Pressure drop [kPa] from Pole's formula."""
    table = _gas_table()
    c = float(pole_constant if pole_constant is not None else table.poleConstant)
    if flow_m3h <= 0:
        return 0.0
    dp_mbar = ((flow_m3h / c) ** 2) * sg * length_m / (bore_mm**5)
    return dp_mbar / 10.0


def gas_velocity_ms(flow_m3h: float, bore_mm: float) -> float:
    """Velocity [m/s] of ``flow_m3h`` in a pipe of internal diameter ``bore_mm``."""
    area = math.pi * (bore_mm / 1000.0) ** 2 / 4.0
    return (flow_m3h / 3600.0) / area if area > 0 else 0.0


def size_gas_pipe(
    flow_m3h: float,
    length_m: float,
    *,
    fuel: str = "naturalGas",
    max_drop_kpa: float | None = None,
    fitting_factor: float | None = None,
) -> dict[str, Any]:
    """Smallest nominal pipe from the pack carrying ``flow_m3h`` over ``length_m`` within
    the allowable pressure drop and velocity limit."""
    table = _gas_table()
    spec = table.fuels[fuel]
    allow_drop = float(max_drop_kpa if max_drop_kpa is not None else spec.maxDropKpa)
    ff = float(fitting_factor if fitting_factor is not None else table.fittingFactor)
    eff_len = max(length_m, 0.1) * ff
    for row in table.pipes:
        dp = pole_drop_kpa(flow_m3h, row.bore, spec.sg, eff_len)
        vel = gas_velocity_ms(flow_m3h, row.bore)
        if dp <= allow_drop + 1e-9 and vel <= table.maxVelocityMs + 1e-9:
            return {
                "nominal": int(row.nominal),
                "bore": row.bore,
                "flowM3h": round(flow_m3h, 3),
                "lengthM": round(length_m, 2),
                "effectiveLengthM": round(eff_len, 2),
                "dropKpa": round(dp, 4),
                "allowableDropKpa": allow_drop,
                "velocityMs": round(vel, 2),
                "ok": True,
            }
    last = table.pipes[-1]
    dp = pole_drop_kpa(flow_m3h, last.bore, spec.sg, eff_len)
    vel = gas_velocity_ms(flow_m3h, last.bore)
    return {
        "nominal": None,
        "bore": last.bore,
        "flowM3h": round(flow_m3h, 3),
        "lengthM": round(length_m, 2),
        "effectiveLengthM": round(eff_len, 2),
        "dropKpa": round(dp, 4),
        "allowableDropKpa": allow_drop,
        "velocityMs": round(vel, 2),
        "ok": False,
    }


def gas_results(mep: Any, building: Any = None) -> dict[str, Any] | None:
    """Fuel gas demand, meter/regulator checks and pipe sizing for ``mep.gas``."""
    gas = getattr(mep, "gas", None)
    if gas is None:
        return None
    table = _gas_table()
    fuel = table.fuels[gas.fuel]
    connected_kw = 0.0
    total_count = 0
    for app in gas.appliances:
        rating = (
            float(app.ratingKw)
            if app.ratingKw is not None
            else float(table.appliances.get(app.kind, 10.0))
        )
        connected_kw += rating * app.count
        total_count += app.count
    div = diversity_factor(total_count, table.diversity)
    diversified_kw = connected_kw * div
    # 1 kW = 3.6 MJ/h
    flow_m3h = (diversified_kw * 3.6) / fuel.cvMjPerM3 if fuel.cvMjPerM3 > 0 else 0.0

    checks: list[dict[str, Any]] = []
    notes: list[str] = []
    if gas.meter is not None:
        in_basement = False
        if building is not None and building.known and gas.meter.story in building.stories:
            in_basement = building.stories[gas.meter.story] < building.ground - 600.0
        if gas.fuel == "lpg" and in_basement:
            checks.append(
                {
                    "name": "LPG meter/cylinder location",
                    "demand": 1.0,
                    "capacity": 0.0,
                    "unit": "",
                    "utilisation": math.inf,
                    "ok": False,
                    "note": "LPG is heavier than air: do not locate cylinders or regulators in a basement",
                }
            )
        else:
            checks.append(
                {
                    "name": "Gas meter/regulator ventilation",
                    "demand": 0.0,
                    "capacity": 0.0,
                    "unit": "",
                    "utilisation": 0.0,
                    "ok": bool(gas.meter.ventilated or gas.meter.outdoor),
                    "note": (
                        "ventilated or outdoor location"
                        if (gas.meter.ventilated or gas.meter.outdoor)
                        else "gas meter/regulator requires a ventilated enclosure or outdoor location"
                    ),
                }
            )

    pipes_out: list[dict[str, Any]] = []
    max_drop = gas.maxDropKpa if gas.maxDropKpa is not None else fuel.maxDropKpa
    for pipe in gas.pipes:
        length_m = max(path_length(pipe.path) / 1000.0, 0.5)
        q = float(pipe.flowM3h) if pipe.flowM3h is not None else flow_m3h
        sized = size_gas_pipe(q, length_m, fuel=gas.fuel, max_drop_kpa=max_drop)
        if pipe.diameter is not None:
            bore = next(
                (r.bore for r in table.pipes if abs(r.nominal - pipe.diameter) < 1e-6),
                float(pipe.diameter),
            )
            dp = pole_drop_kpa(q, bore, fuel.sg, length_m * table.fittingFactor)
            vel = gas_velocity_ms(q, bore)
            ok = dp <= max_drop + 1e-9 and vel <= table.maxVelocityMs + 1e-9
            pipes_out.append(
                {
                    "id": pipe.id,
                    "story": pipe.story,
                    "lengthM": round(length_m, 2),
                    "flowM3h": round(q, 3),
                    "diameter": pipe.diameter,
                    "required": sized["nominal"],
                    "dropKpa": round(dp, 4),
                    "velocityMs": round(vel, 2),
                    "ok": ok,
                }
            )
        else:
            pipes_out.append(
                {
                    "id": pipe.id,
                    "story": pipe.story,
                    "lengthM": round(length_m, 2),
                    "flowM3h": round(q, 3),
                    "diameter": sized["nominal"],
                    "required": sized["nominal"],
                    "dropKpa": sized["dropKpa"],
                    "velocityMs": sized["velocityMs"],
                    "ok": sized["ok"],
                }
            )
    if not gas.pipes and flow_m3h > 0:
        header = size_gas_pipe(flow_m3h, 20.0, fuel=gas.fuel, max_drop_kpa=max_drop)
        notes.append(
            f"estimated 20 m main gas header for {flow_m3h:.2f} m³/h: DN{header['nominal']}"
        )

    return {
        "fuel": gas.fuel,
        "fuelLabel": fuel.label,
        "applianceCount": total_count,
        "connectedKw": round(connected_kw, 2),
        "diversityFactor": div,
        "diversifiedKw": round(diversified_kw, 2),
        "flowM3h": round(flow_m3h, 3),
        "supplyPressureKpa": gas.supplyPressureKpa or fuel.supplyPressureKpa,
        "maxDropKpa": max_drop,
        "pipes": pipes_out,
        "checks": checks,
        "notes": notes,
    }


# ─────────────────────────────────── medical gas ───────────────────────────────────


def medical_gas_flow(gas: str, outlet_count: int) -> dict[str, Any]:
    """Diversified design flow [L/min] for ``outlet_count`` outlets of ``gas``."""
    table = _medgas_table()
    spec = table.gases[gas]
    if outlet_count <= 0:
        return {"gas": gas, "outlets": 0, "diversity": 0.0, "flowLpm": 0.0}
    div = diversity_factor(outlet_count, table.diversity)
    flow = spec.firstLpm + max(outlet_count - 1, 0) * spec.additionalLpm * div
    return {
        "gas": gas,
        "label": spec.label,
        "outlets": outlet_count,
        "diversity": div,
        "flowLpm": round(flow, 1),
    }


def size_medical_gas_pipe(gas: str, flow_lpm: float, length_m: float = 20.0) -> dict[str, Any]:
    """Smallest copper medical gas pipe satisfying max velocity and pressure drop."""
    table = _medgas_table()
    spec = table.gases[gas]
    q_m3s = flow_lpm / 60000.0
    # Approximate gas density at line pressure (air/O2 ~1.25 kg/m³ at 1 bar -> ~6 kg/m³ at 4 bar)
    p_abs_bar = max((abs(spec.supplyPressureKpa) + 101.325) / 100.0, 0.45)
    rho = 1.25 * p_abs_bar
    f_darcy = 0.022
    for row in table.pipes:
        d_m = row.bore / 1000.0
        area = math.pi * d_m * d_m / 4.0
        vel = q_m3s / area if area > 0 else 0.0
        dp_kpa = (f_darcy * (max(length_m, 0.1) / d_m) * 0.5 * rho * vel * vel) / 1000.0
        if vel <= spec.maxVelocityMs + 1e-9 and dp_kpa <= spec.maxDropKpa + 1e-9:
            return {
                "gas": gas,
                "nominal": int(row.nominal),
                "bore": row.bore,
                "flowLpm": round(flow_lpm, 1),
                "velocityMs": round(vel, 2),
                "maxVelocityMs": spec.maxVelocityMs,
                "dropKpa": round(dp_kpa, 3),
                "ok": True,
            }
    last = table.pipes[-1]
    d_m = last.bore / 1000.0
    vel = q_m3s / (math.pi * d_m * d_m / 4.0)
    return {
        "gas": gas,
        "nominal": None,
        "bore": last.bore,
        "flowLpm": round(flow_lpm, 1),
        "velocityMs": round(vel, 2),
        "maxVelocityMs": spec.maxVelocityMs,
        "dropKpa": None,
        "ok": False,
    }


def medical_gas_results(mep: Any, rooms: Any = None) -> dict[str, Any] | None:
    """Medical gas outlet counts, diversified flows and pipe sizes for ``mep.medicalGas``."""
    med = getattr(mep, "medicalGas", None)
    if med is None:
        return None
    table = _medgas_table()
    counts: dict[str, int] = {g: 0 for g in table.gases}
    if med.outlets:
        for o in med.outlets:
            counts[o.gas] = counts.get(o.gas, 0) + o.count
    else:
        for rm in med.rooms:
            for g, n in table.roomOutlets.get(rm.kind, {}).items():
                counts[g] = counts.get(g, 0) + n * rm.beds
        if rooms is not None:
            existing_rooms = {rm.room for rm in med.rooms}
            for room in rooms.rooms:
                if room.id in existing_rooms:
                    continue
                key = room.hvacUse or room.use or ""
                for g, n in table.roomOutlets.get(key, {}).items():
                    counts[g] = counts.get(g, 0) + n

    systems: dict[str, Any] = {}
    for g, n in counts.items():
        if n <= 0:
            continue
        flow_info = medical_gas_flow(g, n)
        sized = size_medical_gas_pipe(g, flow_info["flowLpm"])
        systems[g] = {
            **flow_info,
            "mainPipeMm": sized["nominal"],
            "velocityMs": sized["velocityMs"],
        }

    pipes_out: list[dict[str, Any]] = []
    for p in med.pipes:
        length_m = max(path_length(p.path) / 1000.0, 0.5)
        flow = (
            p.flowLpm if p.flowLpm is not None else (systems.get(p.gas, {}).get("flowLpm") or 0.0)
        )
        sized = size_medical_gas_pipe(p.gas, flow, length_m)
        pipes_out.append(
            {
                "id": p.id,
                "gas": p.gas,
                "story": p.story,
                "lengthM": round(length_m, 2),
                "flowLpm": round(flow, 1),
                "diameter": p.diameter or sized["nominal"],
                "required": sized["nominal"],
                "velocityMs": sized["velocityMs"],
                "ok": sized["ok"],
            }
        )

    return {
        "systems": systems,
        "pipes": pipes_out,
    }

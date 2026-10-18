"""The cooling load estimate when EnergyPlus is not available: "estimate, EnergyPlus not
available".

A steady-state block load per zone, at the design day's maximum dry bulb, from the same inputs
as the EnergyPlus model (:mod:`saengine.hvac.gains`, :mod:`saengine.hvac.constructions`,
:mod:`saengine.hvac.geometry`):

- walls and roof: U A (To - Ti + a I / ho), the sol-air temperature excess with a = 0.7 and
  ho = 17 W/m²K, I the mean daytime irradiance of the facade (N 100, E 300, S 200, W 300 W/m²)
  or of the roof (600 W/m²);
- glazing: U A (To - Ti) + A SHGC I, I the peak irradiance of the facade (N 120, E 500, S 300,
  W 500 W/m²) with only the larger of east and west (they peak at different times); an
  overhang of Sec 4.4.3.1 scales the SHGC by SHGC / (SHGC + A), A of Table 3.4.3 at its
  projection factor 0.234 (BNBC's own equivalence of a shaded window); interior blinds by 0.6;
- exposed floors: U A (To - Ti); floors on the ground and between stories: none;
- people: 75 W sensible and 55 W latent a person at 130 W of activity, in proportion for others;
  lights and equipment: their W/m², all sensible;
- outdoor air: rho V cp (To - Ti) sensible and rho V hfg (Wo - Wi) latent (ASHRAE Fundamentals
  Ch 1 psychrometrics), rho = 1.204 kg/m³ (standard density), cp = 1.006 + 1.86 Wo kJ/kg K,
  hfg = 2501 kJ/kg.

The irradiances, a, ho, the people's split and the blinds' factor are from memory (ASHRAE
Fundamentals load-calculation practice), to be checked; it is an estimate for coordinating the
plant's size and weight, not a design.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.hvac import tables as T
from saengine.hvac.constructions import FLOOR, EnvelopeChoice, u_value
from saengine.hvac.gains import Design, ZoneGains
from saengine.hvac.geometry import ThermalZone

ENGINE = "estimate"
LABEL = "estimate, EnergyPlus not available"

ABSORPTANCE = 0.7
H_OUT = 17.0  # W/m²K
WALL_IRRADIANCE = {"N": 100.0, "E": 300.0, "S": 200.0, "W": 300.0}  # mean daytime, W/m²
ROOF_IRRADIANCE = 600.0
GLASS_IRRADIANCE = {"N": 120.0, "E": 500.0, "S": 300.0, "W": 500.0}  # peak, W/m²
PEOPLE_SENSIBLE, PEOPLE_LATENT, PEOPLE_ACTIVITY = 75.0, 55.0, 130.0
BLINDS = 0.6
RHO = 1.204  # kg/m³, standard density
HFG = 2501.0  # kJ/kg
SUPPLY_DT = 11.0  # K, the design airflow's supply air difference (13 °C supply at 24 °C)


# ─────────────────────────────────── psychrometrics (ASHRAE) ───────────────────────────────────


def pressure(elevation: float) -> float:
    """Standard atmospheric pressure at an elevation [kPa] (ASHRAE Fundamentals Ch 1 Eq 3)."""
    return 101.325 * (1 - 2.25577e-5 * elevation) ** 5.2559


def saturation_pressure(t: float) -> float:
    """Saturation pressure of water vapour over water [kPa] (Hyland-Wexler, ASHRAE
    Fundamentals Ch 1 Eq 6), t in °C (0-200)."""
    k = t + 273.15
    ln = (
        -5.8002206e3 / k + 1.3914993 - 4.8640239e-2 * k + 4.1764768e-5 * k**2
        - 1.4452093e-8 * k**3 + 6.5459673 * math.log(k)
    )  # fmt: skip
    return math.exp(ln) / 1000.0


def humidity_ratio_rh(t: float, rh: float, p: float = 101.325) -> float:
    """Humidity ratio [kg/kg] at a dry bulb [°C] and relative humidity [%]."""
    pw = rh / 100.0 * saturation_pressure(t)
    return 0.621945 * pw / (p - pw)


def humidity_ratio_wb(t: float, wb: float, p: float = 101.325) -> float:
    """Humidity ratio [kg/kg] from the dry and wet bulbs [°C] (ASHRAE Fundamentals Ch 1
    Eq 33)."""
    ws = humidity_ratio_rh(wb, 100.0, p)
    return ((2501 - 2.326 * wb) * ws - 1.006 * (t - wb)) / (2501 + 1.86 * t - 4.186 * wb)


def ventilation_load(
    flow: float, t_out: float, w_out: float, t_in: float, w_in: float
) -> tuple[float, float]:
    """Sensible and latent cooling of outdoor air [kW] (``flow`` m³/s at standard density)."""
    mass = RHO * flow
    sensible = mass * (1.006 + 1.86 * w_out) * (t_out - t_in)
    latent = mass * HFG * max(w_out - w_in, 0.0)
    return sensible, latent


# ─────────────────────────────────────────── loads ───────────────────────────────────────────


def overhang_factor(shgc: float) -> float:
    """SHGC / (SHGC + A) for a Sec 4.4.3.1 overhang (projection factor 0.234, Table 3.4.3's A
    interpolated)."""
    pf = T.OVERHANG_FACTOR
    keys = sorted(T.OVERHANG_A)
    lo = max(k for k in keys if k <= pf)
    hi = min(k for k in keys if k >= pf)
    a = T.OVERHANG_A[lo] if hi == lo else (
        T.OVERHANG_A[lo] + (T.OVERHANG_A[hi] - T.OVERHANG_A[lo]) * (pf - lo) / (hi - lo)
    )  # fmt: skip
    return shgc / (shgc + a)


def zone_load(
    zone: ThermalZone, g: ZoneGains, envelope: EnvelopeChoice, design: Design
) -> dict[str, Any]:
    """The estimate of one conditioned zone [kW]."""
    dt = design.db - g.indoorDB
    u_wall, u_roof, u_floor = envelope.uWall, envelope.uRoof, u_value(FLOOR)
    walls = roof = floors = conduction = 0.0
    solar: dict[str, float] = {}
    shgc = envelope.shgc
    if envelope.shading == "overhang":
        shgc *= overhang_factor(envelope.shgc)
    elif envelope.shading == "blinds":
        shgc *= BLINDS
    for s in zone.surfaces:
        if s.boundary != "Outdoors":
            continue
        if s.kind == "Wall":
            glass = sum(w.area for w in s.windows)
            excess = ABSORPTANCE * WALL_IRRADIANCE[s.facade or "N"] / H_OUT
            walls += u_wall * (s.area - glass) * (dt + excess)
            conduction += envelope.uGlazing * glass * dt
            solar[s.facade or "N"] = (
                solar.get(s.facade or "N", 0.0) + glass * shgc * GLASS_IRRADIANCE[s.facade or "N"]
            )
        elif s.kind == "Roof":
            roof += u_roof * s.area * (dt + ABSORPTANCE * ROOF_IRRADIANCE / H_OUT)
        elif s.kind == "Floor":
            floors += u_floor * s.area * dt
    glass_solar = solar.get("N", 0.0) + solar.get("S", 0.0)
    glass_solar += max(solar.get("E", 0.0), solar.get("W", 0.0))
    scale = g.activity / PEOPLE_ACTIVITY
    people_s = g.occupants * PEOPLE_SENSIBLE * scale
    people_l = g.occupants * PEOPLE_LATENT * scale
    lights = g.lighting * zone.area
    equipment = g.equipment * zone.area
    p = pressure(design.elevation)
    w_out = humidity_ratio_wb(design.db, design.wb, p)
    w_in = humidity_ratio_rh(g.indoorDB, g.indoorRH, p)
    flow = g.outdoor_air(zone.area, zone.volume)
    vent_s, vent_l = ventilation_load(flow, design.db, w_out, g.indoorDB, w_in)
    zone_sensible = (
        walls + roof + floors + conduction + glass_solar + people_s + lights + equipment
    ) / 1000.0
    sensible = zone_sensible + vent_s
    latent = people_l / 1000.0 + vent_l
    airflow = max(zone_sensible / (RHO * 1.006 * SUPPLY_DT), flow)
    return {
        "sensible": sensible,
        "latent": latent,
        "total": sensible + latent,
        "airflow": airflow,
        "outdoorAir": flow,
        "peak": {"designDay": None, "month": None, "time": None, "outdoorDB": design.db,
                 "outdoorW": w_out},
        "breakdown": {
            "walls": walls / 1000.0,
            "roof": roof / 1000.0,
            "floors": floors / 1000.0,
            "glazingConduction": conduction / 1000.0,
            "glazingSolar": glass_solar / 1000.0,
            "people": (people_s + people_l) / 1000.0,
            "lights": lights / 1000.0,
            "equipment": equipment / 1000.0,
            "infiltration": 0.0,
            "ventilation": vent_s + vent_l,
        },
    }  # fmt: skip

"""HVAC cooling load benchmarks (stream H1): the outdoor air load and the estimate by hand, and
EnergyPlus's conduction and ventilation against the steady-state formulas.

The buildings are synthetic: a single 10 x 10 m story 3 m high (:func:`box_bim`) and, for the
estimate, the same box with a south window. DH1 and DH2 run without EnergyPlus and are part of
the fast pack; AH1 needs EnergyPlus version 26.2.0 and reports itself skipped (no quantities)
when it is not found.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from saengine.hvac import energyplus as EP
from saengine.hvac import fallback as F
from saengine.hvac.constructions import envelope as envelope_choice
from saengine.hvac.gains import design_conditions, zone_gains
from saengine.hvac.geometry import zones
from saengine.library.bim import BuildingModel
from saengine.library.mep import MepModel
from saengine.plumbing.building import Building
from saengine.verification.cases.common import Case, Outcome, Quantity, Reference

EXACT = 0.005
L, W, H = 10.0, 10.0, 3.0  # m


def box_bim(length: float = L * 1000, width: float = W * 1000, height: float = H * 1000):
    """A ground story GF and its roof slab at ``height`` over a ``length`` x ``width`` plan."""
    return BuildingModel.model_validate({
        "stories": [{"id": "GF", "name": "GF", "elevation": 0},
                    {"id": "ROOF", "name": "ROOF", "elevation": height}],
        "elements": [{"id": "S-ROOF", "type": "SL150", "kind": "slab", "elevation": height,
                      "boundary": [[0, 0], [length, 0], [length, width], [0, width]]}],
    })  # fmt: skip


def box_mep(story: dict[str, Any], design: dict[str, Any] | None = None, **envelope: Any):
    return MepModel.model_validate(
        {"hvac": {"design": design or {}, "envelope": envelope, "stories": [story]}}
    )


def _zone(mep: MepModel, bim: BuildingModel):
    zoning = zones(Building.of(bim), mep.hvac)
    return zoning.zones[0]


# ───────────────────────────── DH1: outdoor air load by hand ─────────────────────────────


def _magnus(t: float) -> float:
    """Saturation vapour pressure [kPa], Magnus-Tetens (Alduchov and Eskridge 1996)."""
    return 0.61094 * math.exp(17.625 * t / (t + 243.04))


def ventilation_case(folder: Path) -> Outcome:
    """Office floor 20 x 15 m: Table 8.2.3 office spaces, 5 persons per 100 m², 2.5 l/s a
    person + 0.3 l/s per m²; Dhaka 2 % (34.5 °C DB, 27.0 °C MWB) to 24 °C, 60 % RH."""
    bim = box_bim(20000, 15000, 3000)
    mep = box_mep({"story": "GF", "use": "officeSpace"})
    zone = _zone(mep, bim)
    g = zone_gains(zone, mep.hvac)
    design = design_conditions(mep.hvac, "dhaka")
    flow = g.outdoor_air(zone.area, zone.volume)
    p = F.pressure(design.elevation)
    w_out = F.humidity_ratio_wb(design.db, design.wb, p)
    w_in = F.humidity_ratio_rh(g.indoorDB, g.indoorRH, p)
    sensible, latent = F.ventilation_load(flow, design.db, w_out, g.indoorDB, w_in)
    # The reference: hand arithmetic with other formulas than SAEngine's.
    persons = 5 * 300 / 100  # 15
    v = 2.5 * persons + 0.3 * 300  # l/s
    p_hand = 101.325 * (1 - 2.25577e-5 * 10) ** 5.2559
    # Wet-bulb psychrometer (Sprung): e = es(Twb) - A p (T - Twb), A = 6.62e-4 /K.
    e_out = _magnus(27.0) - 6.62e-4 * p_hand * (34.5 - 27.0)
    wo = 0.622 * e_out / (p_hand - e_out)
    e_in = 0.60 * _magnus(24.0)
    wi = 0.622 * e_in / (p_hand - e_in)
    qs = 1.23 * v * (34.5 - 24.0) / 1000.0  # ASHRAE Fundamentals Ch 18: qs = 1.23 Q dt
    ql = 3010 * v * (wo - wi) / 1000.0  # ql = 3010 Q dW
    return Outcome(
        Reference(
            "BNBC 2020 Part 8 Table 8.2.3 (office spaces) and Table 8.2.2 (Dhaka 2 %); ASHRAE "
            "Handbook of Fundamentals Ch 18 air-load equations; Magnus-Tetens and Sprung "
            "psychrometric formulas.",
            "Vbz = Rp Pz + Ra Az; qs = 1.23 Q dt; ql = 3010 Q dW (Q in l/s)",
            [
                f"Pz = 5 / 100 m² x 300 m² = {persons:g} persons",
                f"Vbz = 2.5 x {persons:g} + 0.3 x 300 = {v:g} l/s",
                f"Wo (34.5 °C, 27.0 °C wb) = {wo:.5f}; Wi (24 °C, 60 %) = {wi:.5f} kg/kg",
                f"qs = 1.23 x {v:g} x 10.5 = {qs * 1000:.0f} W",
                f"ql = 3010 x {v:g} x {wo - wi:.5f} = {ql * 1000:.0f} W",
            ],
        ),
        [
            Quantity("Occupants", "persons", persons, g.occupants, EXACT),
            Quantity("Outdoor air", "l/s", v, flow * 1000.0, EXACT),
            Quantity("Outdoor humidity ratio", "g/kg", wo * 1000, w_out * 1000, 0.02),
            Quantity("Indoor humidity ratio", "g/kg", wi * 1000, w_in * 1000, 0.02),
            Quantity("Ventilation sensible load", "kW", qs, sensible, 0.03),
            Quantity("Ventilation latent load", "kW", ql, latent, 0.04),
        ],
        [
            (
                "SAEngine uses the Hyland-Wexler saturation pressure and the ASHRAE wet-bulb "
                "equation; the reference Magnus-Tetens and the Sprung psychrometer constant, so "
                "the humidity ratios agree within about 1 %."
            ),
        ],
    )


# ───────────────────────────── DH2: the estimate by hand ─────────────────────────────


def estimate_case(folder: Path) -> Outcome:
    """The 10 x 10 x 3 m box: 250 mm brick walls, lime-terraced RC roof, single clear glass on
    the south (window-to-wall ratio 0.3, none elsewhere), 5 office occupants, 9 W/m² lights,
    10.8 W/m² equipment; Dhaka 2 %."""
    bim = box_bim()
    story = {"story": "GF", "use": "officeSpace", "lighting": 9, "equipment": 10.8,
             "glazing": {"N": 0, "E": 0, "S": 0.3, "W": 0}}  # fmt: skip
    mep = box_mep(story)
    zone = _zone(mep, bim)
    g = zone_gains(zone, mep.hvac)
    env = envelope_choice(mep.hvac.envelope)
    design = design_conditions(mep.hvac, "dhaka")
    est = F.zone_load(zone, g, env, design)
    # By hand: four 10 x 3 m walls, the south one with 9 m² of glass; a 100 m² roof.
    dt = 34.5 - 24.0
    r_wall = 2 * 0.012 / 1.4 + 0.250 / 0.895
    u_wall = 1 / (0.13 + r_wall + 0.04)
    r_roof = 0.100 / 0.97 + 0.150 / 2.15 + 0.012 / 1.4
    u_roof = 1 / (0.17 + r_roof + 0.04)
    wall_area = 10 * 3.0
    glass = 0.3 * wall_area
    excess = {f: 0.7 * i / 17 for f, i in {"N": 100, "E": 300, "S": 200, "W": 300}.items()}
    walls = u_wall * (
        sum(wall_area * (dt + excess[f]) for f in ("N", "E", "W"))
        + (wall_area - glass) * (dt + excess["S"])
    )
    roof = u_roof * 100 * (dt + 0.7 * 600 / 17)
    conduction = 5.778 * glass * dt
    solar = glass * 0.819 * 300
    people = 5 * (75 + 55)
    lights, equipment = 9 * 100, 10.8 * 100
    sensible_zone = (walls + roof + conduction + solar + 5 * 75 + lights + equipment) / 1000
    return Outcome(
        Reference(
            "SAEngine's documented estimate (saengine.hvac.fallback) worked out by hand: U-values "
            "from the EnergyPlus version 26.2.0 data set materials with ISO 6946 surface "
            "resistances; sol-air excess a I / ho; glass U A dt + A SHGC I.",
            "q = U A (dt + a I / ho) + Ug Ag dt + Ag SHGC I + people + lights + equipment",
            [
                f"U wall = 1 / (0.13 + {r_wall:.4f} + 0.04) = {u_wall:.3f} W/m²K",
                f"U roof = 1 / (0.17 + {r_roof:.4f} + 0.04) = {u_roof:.3f} W/m²K",
                f"glass {glass:g} m² on the south, walls 4 x {wall_area:g} m²",
                f"walls {walls:.0f} W, roof {roof:.0f} W, glass {conduction:.0f} + {solar:.0f} W",
                f"people 5 x (75 + 55) W, lights {lights:g} W, equipment {equipment:g} W",
            ],
        ),
        [
            Quantity("Walls", "kW", walls / 1000, est["breakdown"]["walls"], EXACT),
            Quantity("Roof", "kW", roof / 1000, est["breakdown"]["roof"], EXACT),
            Quantity(
                "Glass conduction",
                "kW",
                conduction / 1000,
                est["breakdown"]["glazingConduction"],
                EXACT,
            ),
            Quantity("Glass solar", "kW", solar / 1000, est["breakdown"]["glazingSolar"], EXACT),
            Quantity("People", "kW", people / 1000, est["breakdown"]["people"], EXACT),
            Quantity(
                "Zone sensible (without outdoor air)",
                "kW",
                sensible_zone,
                est["sensible"] - _vent(g, design, zone)[0],
                EXACT,
            ),
        ],
        [
            (
                "The estimate's irradiances, absorptance and film coefficients are from memory, "
                "to be checked; the case checks the arithmetic, not those values."
            )
        ],
    )


def _vent(g: Any, design: Any, zone: Any) -> tuple[float, float]:
    """The estimate's own outdoor air load (sensible, latent) [kW]: DH1 checks it."""
    p = F.pressure(design.elevation)
    w_out = F.humidity_ratio_wb(design.db, design.wb, p)
    w_in = F.humidity_ratio_rh(g.indoorDB, g.indoorRH, p)
    flow = g.outdoor_air(zone.area, zone.volume)
    return F.ventilation_load(flow, design.db, w_out, g.indoorDB, w_in)


# ─────────────────────── AH1: EnergyPlus against the steady state ───────────────────────

H_IN, H_OUT = 8.0, 25.0  # W/m²K, fixed for the case


def steady_box_model(oa_per_area: bool = True) -> tuple[Any, dict[str, Any]]:
    """The box as EnergyPlus sees it, made steady: a constant outdoor 34.5 °C (daily range 0),
    no sun on its walls, its roof adiabatic, no windows, no internal gains, fixed film
    coefficients (inside 8, outside 25 W/m²K) and no long-wave radiation (emissivity 0.001);
    Table 8.2.3 corridor outdoor air (0.3 l/s per m²) when ``oa_per_area``."""
    bim = box_bim()
    use = "corridor" if oa_per_area else "dwellingToilet"
    story = {"story": "GF", "use": use, "occupants": 0, "lighting": 0, "equipment": 0,
             "glazing": {"N": 0, "E": 0, "S": 0, "W": 0}}  # fmt: skip
    mep = box_mep(story, {"dailyRange": 0})
    zoning = zones(Building.of(bim), mep.hvac)
    gains = {z.name: zone_gains(z, mep.hvac) for z in zoning.zones}
    env = envelope_choice(mep.hvac.envelope)
    design = design_conditions(mep.hvac, "dhaka")
    model = EP.build(zoning.zones, gains, env, design)
    m = model.epjson
    for material in m["Material"].values():
        material["thermal_absorptance"] = 0.001
    for surface in m["BuildingSurface:Detailed"].values():
        surface["sun_exposure"] = "NoSun"
        if surface["surface_type"] == "Roof":
            surface["outside_boundary_condition"] = "Adiabatic"
            surface["wind_exposure"] = "NoWind"
    # The adiabatic floor and roof get the inside film too, so that they settle at the zone
    # air temperature within the warm-up days (store no heat at the peak).
    m["SurfaceProperty:ConvectionCoefficients"] = {
        f"{name} film": {
            "surface_name": name,
            "convection_coefficient_1_location": "Inside",
            "convection_coefficient_1_type": "Value",
            "convection_coefficient_1": H_IN,
        }
        for name, surface in m["BuildingSurface:Detailed"].items()
        if surface["surface_type"] in ("Floor", "Roof")
    }
    m["SurfaceProperty:ConvectionCoefficients:MultipleSurface"] = {
        "Fixed films": {
            "surface_type": "AllExteriorWalls",
            "convection_coefficient_1_location": "Inside",
            "convection_coefficient_1_type": "Value",
            "convection_coefficient_1": H_IN,
            "convection_coefficient_2_location": "Outside",
            "convection_coefficient_2_type": "Value",
            "convection_coefficient_2": H_OUT,
        }
    }
    return model, {"zone": zoning.zones[0], "gains": gains, "design": design}


def energyplus_case(folder: Path) -> Outcome:
    exe = EP.find_energyplus()
    reference = Reference(
        "Steady one-dimensional conduction U A (To - Ti) through the plastered 250 mm brick "
        "walls (EnergyPlus data set materials) with the fixed films; the outdoor air load "
        "rho V cp (To - Ti) and rho V hfg (Wo - Wi).",
        "q = A (To - Ti) / (1/hi + sum t/k + 1/ho); qs = rho V cp dT; ql = rho V hfg dW",
    )
    if exe is None:
        return Outcome(reference, [], ["Skipped: EnergyPlus version 26.2.0 was not found."])
    model, parts = steady_box_model()
    result = EP.run(model, exe, folder / "energyplus")
    zone = result["zones"][parts["zone"].name]
    r = 2 * 0.012 / 1.4 + 0.250 / 0.895
    u = 1 / (1 / H_IN + r + 1 / H_OUT)
    area = 4 * L * H
    conduction = u * area * (34.5 - 24.0) / 1000.0
    flow = 0.3 * L * W / 1000.0
    w_out = zone["peak"]["outdoorW"]  # EnergyPlus's own outdoor humidity ratio
    w_in = zone["peak"]["zoneW"]  # and the zone's (see the notes)
    vs = 1.204 * flow * (1.006 + 1.86 * w_out) * (34.5 - 24.0)
    vl = 1.204 * flow * 2501 * (w_out - w_in)
    reference.steps = [
        f"U = 1 / (1/{H_IN:g} + {r:.4f} + 1/{H_OUT:g}) = {u:.4f} W/m²K over {area:g} m²",
        f"q = {u:.4f} x {area:g} x 10.5 = {conduction * 1000:.0f} W",
        (
            f"V = 0.3 l/s m² x 100 m² = {flow * 1000:g} l/s; Wo = {w_out:.5f}, Wi = {w_in:.5f} "
            "kg/kg (EnergyPlus's outdoor air and zone air)"
        ),
        (
            f"qs = 1.204 x {flow:g} x (1.006 + 1.86 Wo) x 10.5 = {vs * 1000:.0f} W; "
            f"ql = 1.204 x {flow:g} x 2501 x dW = {vl * 1000:.0f} W"
        ),
    ]
    return Outcome(
        reference,
        [
            Quantity("Wall conduction (zone load)", "kW", conduction, zone["zoneTotal"], 0.02),
            Quantity("Outdoor air", "m³/s", flow, zone["ventilation"]["flow"], EXACT),
            Quantity("Ventilation sensible", "kW", vs, zone["ventilation"]["sensible"], 0.03),
            Quantity("Ventilation latent", "kW", vl, zone["ventilation"]["latent"], 0.03),
        ],
        [
            (
                "Steady state: a constant outdoor temperature over the design day, so after "
                "EnergyPlus's warm-up days the dynamic conduction equals the steady one; 2 % covers "
                "the warm-up convergence. The inside film is fixed on the adiabatic floor and roof "
                "too, so that they store no heat at the peak."
            ),
            (
                "The zone's humidity ratio is EnergyPlus's: the ideal loads coil supplies saturated "
                "air at 13 °C, which holds the zone below its 60 % humidistat (about 50 %); the "
                "latent load is the coil's. The formulas' moist-air cp and hfg = 2501 kJ/kg differ "
                "from EnergyPlus's enthalpy by about 2 %."
            ),
        ],
    )


CASES = [
    Case(
        "DH1",
        "HVAC: outdoor air load of an office floor",
        "design",
        "Outdoor air of BNBC 2020 Table 8.2.3 for an office floor and its sensible and latent "
        "cooling at the Dhaka design condition of Table 8.2.2.",
        "Office floor 20 x 15 m, default occupancy; saengine.hvac.gains and saengine.hvac."
        "fallback.ventilation_load.",
        ventilation_case,
    ),
    Case(
        "DH2",
        "HVAC: the cooling load estimate of a box",
        "design",
        "The estimate SAEngine gives when EnergyPlus is not available, component by component, "
        "against the hand arithmetic.",
        "Box 10 x 10 x 3 m, brick walls, lime-terraced roof, a south window of 30 % of the wall; "
        "saengine.hvac.fallback.zone_load.",
        estimate_case,
    ),
    Case(
        "AH1",
        "HVAC: EnergyPlus conduction and ventilation in the steady state",
        "analysis",
        "EnergyPlus version 26.2.0's cooling load of a box with only wall conduction and outdoor "
        "air, made steady, against U A dT and the air-load formulas.",
        "Box 10 x 10 x 3 m, plastered 250 mm brick walls, fixed films, constant 34.5 °C outside, "
        "0.3 l/s per m² outdoor air; saengine.hvac.energyplus. Skipped without EnergyPlus.",
        energyplus_case,
        fast=False,
    ),
]

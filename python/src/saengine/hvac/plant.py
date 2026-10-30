"""HVAC plant sized for the structure: what stands on the floors and roof, and what it weighs.

The structural engineer coordinates the plant's weight, footprint and vibration (BNBC 2020
Part 8 Sec 2.6.2.4 and 2.6.2.5, pp. 853-854 of the Part 2 volume: plant rooms, roof chillers
"structurally strong enough to withstand the dynamic load of the chiller", vibration
isolators; clear headroom below beam soffits of at least 4.5 m for centrifugal and 3.6 m for
reciprocating and screw chillers in water-cooled chiller installations of 500 TR (1758 kW)
and above, Sec 2.6.2.4(b): SAEngine takes the installed capacity, duty and standby units
together). This module proposes the
plant of the system ``hvac.system`` from the zone loads and airflows (:mod:`saengine.hvac.air`)
as 07 MEP ``hvac.plant`` entries with ``"sized": true``:

- Plant capacity: the sum of the zones' total loads times a diversity of 0.9 for more than
  one zone (the zones do not peak together) and a margin of 1.1 (SAEngine practice).
- Chilled water: chillers air-cooled on the roof below 1050 kW, water-cooled (screw up to
  1050 kW a unit, centrifugal above) in a plant room on the lowest story from 1050 kW (the
  size categories of BNBC Table 8.2.11, p. 919); at least two duty units from 350 kW and one
  more on standby (N + 1, SAEngine practice; the standby unit's weight is on the structure).
  Cooling towers (water-cooled) reject the heat of their chiller, Q (1 + 1/COP), with the
  minimum COP of BNBC Table 8.2.11 for its class and size; condenser water at 5.6 K range,
  chilled water at 5.6 K (12.2/6.7 °C: SAEngine defaults, from memory). Primary chilled water
  and condenser water pumps, one per chiller.
- VRF: outdoor units of up to 56 kW modules on the roof (from memory, to be checked), split:
  one outdoor unit per 7 kW, packaged: rooftop units of up to 100 kW.
- AHUs (chilled water: one per conditioned story at its supply airflow; packaged systems
  have none) sized by a coil face velocity of 2.5 m/s (SAEngine practice); fresh-air units per
  story for VRF and split systems at the story's outdoor air; an exhaust fan on the roof at the
  top of every exhaust and kitchen exhaust riser.
- Dimensions and operating weights are TYPICAL VALUES FROM MEMORY OF MANUFACTURERS'
  CATALOGUES, to be checked and replaced with the selected unit's data (:data:`TYPICAL`).
- Riser pipes: chilled and condenser water mains (steel) by velocity (at most 3 m/s) and
  friction (at most 400 Pa/m) with ``fluids``; refrigerant pipe pairs of VRF by capacity
  (from memory). Their sleeves through the slabs are the pipe's outside diameter plus twice
  the insulation plus 50 mm, the next standard size (the plumbing sleeve rule,
  :mod:`saengine.plumbing.sleeves`).

The plant becomes loads through 07 MEP's equipment path: stream H1's
:func:`saengine.hvac.report.plant_equipment` turns a plant entry into an equipment item,
vibrating for the rotating machines (BNBC Table 6.2.6 impact allowance applied by
:mod:`saengine.mep.loads`).
"""

from __future__ import annotations

import math
from typing import Any

from shapely.geometry import Point

from saengine.mep.geometry import bounded_id

DIVERSITY = 0.9
MARGIN = 1.10
WATER_DT = 5.6  # K, chilled and condenser water (SAEngine default)
CW = 4.186  # kJ/(kg K)
FACE_VELOCITY = 2.5  # m/s across the AHU coil (SAEngine practice)
SPACING = 1500.0  # mm clear between units in a row (SAEngine practice, for maintenance)
WATER_COOLED_FROM = 1050.0  # kW: BNBC Table 8.2.11's largest size category
TWO_UNITS_FROM = 350.0  # kW
INSTALLATION_500TR = 1758.0  # kW: 500 TR x 3.517, BNBC Sec 2.6.2.4(b) (the installation)
#: Largest unit [kW] SAEngine proposes of each kind.
UNIT_MAX = {
    "airCooled": 1400.0,
    "screw": 1050.0,
    "centrifugal": 3500.0,
    "vrfOutdoor": 56.0,
    "splitOutdoor": 7.0,
    "packaged": 100.0,
}
#: BNBC 2020 Part 8 Table 8.2.11 (p. 919), minimum COP: (upper bound kW, COP).
COP_TABLE_8211 = {
    "airCooled": [(530.0, 2.90), (math.inf, 3.05)],
    "centrifugal": [(530.0, 5.80), (1050.0, 5.80), (math.inf, 6.30)],
    "screw": [(530.0, 4.70), (1050.0, 5.40), (math.inf, 5.75)],
}
#: TYPICAL operating weight and size of plant (from memory of manufacturers' catalogues, to be
#: checked; replace with the selected unit's data): kN per kW (cooling, or heat rejected for
#: towers), plan area m² per kW, a typical width and height [mm].
TYPICAL = {
    "airCooled": {"weight": 0.100, "area": 0.022, "width": 2300.0, "height": 2500.0},
    "screw": {"weight": 0.065, "area": 0.0081, "width": 1800.0, "height": 2200.0},
    "centrifugal": {"weight": 0.055, "area": 0.0039, "width": 2500.0, "height": 3000.0},
    "coolingTower": {"weight": 0.060, "area": 0.0123, "width": None, "height": 4000.0},
    "vrfOutdoor": {"weight": 0.060, "area": 0.0168, "width": 760.0, "height": 1690.0},
    "splitOutdoor": {"weight": 0.070, "area": 0.039, "width": 320.0, "height": 600.0},
    "packaged": {"weight": 0.150, "area": 0.099, "width": 2200.0, "height": 1400.0},
}
#: Pumps (end suction with motor on an inertia base), TYPICAL: (flow up to l/s, kN, L, W).
PUMPS = [
    (10.0, 2.5, 1500.0, 800.0),
    (30.0, 5.0, 1800.0, 900.0),
    (60.0, 8.0, 2100.0, 1000.0),
    (120.0, 12.0, 2400.0, 1200.0),
    (math.inf, 18.0, 2800.0, 1400.0),
]
#: AHU, TYPICAL: kN = AHU_BASE + AHU_PER * airflow [m³/s]; length by airflow.
AHU_BASE, AHU_PER = 3.0, 4.5
FAN_BASE, FAN_PER = 0.5, 0.3  # roof exhaust fan, kN
#: Steel pipe nominal sizes [mm] and the limits of the water mains.
PIPE_SIZES = [25, 32, 40, 50, 65, 80, 100, 125, 150, 200, 250, 300, 350, 400, 450, 500]
PIPE_VMAX = 3.0  # m/s (from memory, ASHRAE Handbook Fundamentals Ch 22)
PIPE_FRICTION = 400.0  # Pa/m
PIPE_ROUGHNESS = 0.046  # mm, commercial steel
PIPE_INSULATION = 40.0  # mm, chilled water (SAEngine default)
#: VRF refrigerant pipe pair (gas, liquid) outside diameters [mm] by system capacity [kW]
#: (from memory of manufacturers' piping tables, to be checked).
REFRIGERANT = [
    (22.4, 15.88, 9.52),
    (45.0, 22.22, 12.7),
    (70.0, 28.58, 15.88),
    (100.0, 31.75, 19.05),
    (150.0, 38.1, 19.05),
    (math.inf, 41.28, 22.22),
]
REFRIGERANT_INSULATION = 19.0  # mm
TYPICAL_NOTE = "typical catalogue value; replace with the selected unit's data"


def plant_capacity(zones: list[dict[str, Any]], coincident: float | None = None) -> dict:
    """Cooling capacity of the plant [kW]: the coincident peak of all zones when the load
    calculation gives one (EnergyPlus), else the sum of the zones' peaks x a diversity of 0.9
    (more than one zone), times the margin 1.1 (SAEngine practice)."""
    totals = [z.get("total") or z.get("sensible") or 0.0 for z in zones]
    total = sum(totals)
    if coincident and coincident > 0:
        return {
            "sum": total, "coincident": coincident, "diversity": 1.0, "margin": MARGIN,
            "capacity": coincident * MARGIN,
            "note": f"coincident peak of the zones {coincident:.0f} kW (the load calculation) x "
            f"margin {MARGIN:g} (SAEngine practice)",
        }  # fmt: skip
    diversity = DIVERSITY if len([t for t in totals if t > 0]) > 1 else 1.0
    return {
        "sum": total,
        "coincident": None,
        "diversity": diversity,
        "margin": MARGIN,
        "capacity": total * diversity * MARGIN,
        "note": f"sum of {len(totals)} zone loads x diversity {diversity:g} x margin "
        f"{MARGIN:g} (SAEngine practice)",
    }


def chiller_cop(kind: str, unit_kw: float) -> float:
    """The minimum COP of BNBC Table 8.2.11 of a chiller class and size."""
    for upper, cop in COP_TABLE_8211[kind]:
        if unit_kw < upper:
            return cop
    return COP_TABLE_8211[kind][-1][1]


def heat_rejection(cooling_kw: float, cop: float) -> float:
    """Heat a cooling tower rejects [kW]: the cooling plus the compressor work, Q (1 + 1/COP)."""
    return cooling_kw * (1 + 1 / cop)


def water_flow(kw: float, dt: float = WATER_DT) -> float:
    """Water flow [l/s] that carries ``kw`` at a ``dt`` K rise."""
    return kw / (CW * dt)


def chiller_plan(capacity: float, standby: bool = True) -> dict[str, Any]:
    """Chiller class, number and unit size for a plant ``capacity`` [kW]."""
    if capacity >= WATER_COOLED_FROM:
        n = max(2, math.ceil(capacity / UNIT_MAX["centrifugal"]))
        unit = capacity / n
        kind = "screw" if unit <= UNIT_MAX["screw"] else "centrifugal"
        if kind == "screw":
            n = max(2, math.ceil(capacity / UNIT_MAX["screw"]))
            unit = capacity / n
    else:
        kind = "airCooled"
        n = max(2 if capacity >= TWO_UNITS_FROM else 1, math.ceil(capacity / UNIT_MAX[kind]))
        unit = capacity / n
    unit = math.ceil(unit / 5.0 - 1e-6) * 5.0
    return {"kind": kind, "duty": n, "standby": 1 if standby and n >= 2 else 0, "unit": unit,
            "cop": chiller_cop(kind, unit)}  # fmt: skip


def _box(kind: str, kw: float) -> tuple[float, float, float, float]:
    """(length, width, height [mm], operating weight [kN]) of a unit, TYPICAL."""
    t = TYPICAL[kind]
    area = t["area"] * kw * 1e6
    width = t["width"] or math.sqrt(area)
    length = max(area / width, width if t["width"] is None else 0.0)
    return round(length / 10) * 10, round(width / 10) * 10, t["height"], t["weight"] * kw


def pump(flow_ls: float) -> tuple[float, float, float]:
    """(length, width [mm], operating weight [kN]) of a pump set, TYPICAL."""
    for upper, weight, length, width in PUMPS:
        if flow_ls <= upper:
            return length, width, weight
    return PUMPS[-1][2], PUMPS[-1][3], PUMPS[-1][1]


def ahu_size(airflow: float) -> dict[str, float]:
    """Face area [m²] at 2.5 m/s, casing size [mm] and operating weight [kN] of an AHU."""
    face = airflow / FACE_VELOCITY
    coil_h = min(2400.0, max(600.0, math.sqrt(face / 1.6) * 1000))
    coil_w = face * 1e6 / coil_h
    return {
        "face": face,
        "width": math.ceil((coil_w + 300) / 50) * 50,
        "height": math.ceil((coil_h + 300) / 50) * 50,
        "length": 4500.0 if airflow <= 5.0 else 6000.0,
        "weight": AHU_BASE + AHU_PER * airflow,
    }


def pipe_size(flow_ls: float) -> dict[str, Any]:
    """The smallest steel main (nominal bore) carrying ``flow_ls`` within the velocity and
    friction limits: ``{"nominal", "velocity", "friction"}``."""
    from fluids.friction import friction_factor

    for nominal in PIPE_SIZES:
        d = nominal / 1000.0
        v = flow_ls / 1000.0 / (math.pi * d * d / 4)
        re = 1000.0 * v * d / 1.3e-3
        f = friction_factor(Re=re, eD=PIPE_ROUGHNESS / nominal)
        friction = f / d * 1000.0 * v * v / 2
        if v <= PIPE_VMAX and friction <= PIPE_FRICTION:
            return {"nominal": float(nominal), "velocity": v, "friction": friction}
    return {"nominal": float(PIPE_SIZES[-1]), "velocity": None, "friction": None}


def pipe_sleeve(nominal: float, insulation: float = PIPE_INSULATION) -> float:
    """Sleeve [mm] of an insulated steel pipe: OD + 2 insulation + 50, next standard size."""
    from saengine.plumbing import tables as T
    from saengine.plumbing.sleeves import outside_diameter

    need = outside_diameter(nominal, "GI") + 2 * insulation + T.SLEEVE_CLEARANCE
    for size in T.SLEEVE_SIZES:
        if size >= need - 1e-9:
            return float(size)
    return float(math.ceil(need / 50.0) * 50.0)


def refrigerant_pair(capacity_kw: float) -> dict[str, Any]:
    for upper, gas, liquid in REFRIGERANT:
        if capacity_kw <= upper:
            break
    from saengine.plumbing import tables as T

    need = gas + liquid + 4 * REFRIGERANT_INSULATION + T.SLEEVE_CLEARANCE
    sleeve = next((float(s) for s in T.SLEEVE_SIZES if s >= need - 1e-9), math.ceil(need / 50) * 50)
    return {"gas": gas, "liquid": liquid, "sleeve": sleeve}


# ─────────────────────────────────────── placement ───────────────────────────────────────


def _row(
    project: Any, story: str, units: list[dict[str, Any]], notes: list[str]
) -> list[dict[str, Any]]:
    """Places ``units`` (with length and width) in a row along X centred on the story's
    slabs (SAEngine's first placement: move them to the plant's real place)."""
    roof = project.building.roof(story) if project.building.known else None
    if roof is None or roof.is_empty:
        cx = cy = 0.0
    else:
        cx, cy = roof.centroid.x, roof.centroid.y
    total = sum(u["length"] for u in units) + SPACING * max(len(units) - 1, 0)
    x = cx - total / 2
    for u in units:
        u["x"] = round(x + u["length"] / 2)
        u["y"] = round(cy)
        x += u["length"] + SPACING
        if roof is not None and not roof.is_empty and not roof.covers(Point(u["x"], u["y"])):
            notes.append(f"{u['id']}: placed outside the slabs of {story}: move it")
    return units


def _top(project: Any) -> str | None:
    order = project.order
    return order[-1] if order else None


def _bottom(project: Any) -> str | None:
    order = project.order
    return order[0] if order else None


def _entry(uid: str, kind: str, story: str, length, width, height, capacity, weight, **extra):
    return {"id": uid, "kind": kind, "story": story, "x": 0.0, "y": 0.0,
            "length": float(length), "width": float(width), "height": float(height),
            # Rounded up, so that a proposed unit always gives what it was sized for.
            "capacity": math.ceil(float(capacity) * 100 - 1e-6) / 100 if capacity and capacity > 0 else None,
            "operatingWeight": round(float(weight), 1),
            "sized": True, **extra}  # fmt: skip


# ─────────────────────────────────────── the proposal ───────────────────────────────────────


def propose_plant(
    project: Any,
    zones: list[dict[str, Any]],
    standby: bool = True,
    coincident: float | None = None,
) -> dict:
    """The proposed plant of the project's ``hvac.system`` for ``zones`` (from
    :func:`saengine.hvac.air.zone_air`): ``{"plant": [07 MEP hvac.plant entries, "sized":
    true], "equipment": [the same as 07 MEP equipment for the loads], "pipes": [riser mains
    and their sleeves], "capacity", "checks", "notes"}``. Entries the engineer placed (not
    ``sized``) are kept: SAEngine fills their capacity and weight where missing (with their
    ids) and proposes no others of that kind."""
    hvac = project.hvac
    system = hvac.get("system", "none")
    notes: list[str] = []
    checks: list[dict[str, Any]] = []
    pipes: list[dict[str, Any]] = []
    all_zones = zones  # with the stories that are not conditioned (their exhaust)
    zones = [z for z in zones if z.get("conditioned", True)]
    if system == "none" or not zones:
        return {"plant": [], "equipment": [], "pipes": [], "capacity": None, "checks": [],
                "notes": [] if system == "none" else ["no zone loads: no plant proposed"]}  # fmt: skip
    cap = plant_capacity(zones, coincident)
    q = cap["capacity"]
    notes.append(f"plant capacity {q:.0f} kW: {cap['note']}")
    top, bottom = _top(project), _bottom(project)
    proposed: dict[str, list[dict[str, Any]]] = {}

    def add(kind: str, story: str | None, units: list[dict[str, Any]]) -> None:
        if story is None or not units:
            return
        proposed.setdefault(kind, []).extend(_row(project, story, units, notes))

    if system == "chilledWater":
        plan = chiller_plan(q, standby)
        n = plan["duty"] + plan["standby"]
        story = top if plan["kind"] == "airCooled" else bottom
        length, width, height, weight = _box(plan["kind"], plan["unit"])
        chillers = [
            _entry(f"CH{i + 1}", "chiller", story, length, width, height, plan["unit"], weight)
            for i in range(n)
        ]
        add("chiller", story, chillers)
        label = {"airCooled": "air-cooled screw", "screw": "water-cooled screw",
                 "centrifugal": "water-cooled centrifugal"}[plan["kind"]]  # fmt: skip
        notes.append(
            f"{plan['duty']} duty + {plan['standby']} standby {label} chillers of "
            f"{plan['unit']:g} kW, COP {plan['cop']:g} (BNBC Table 8.2.11 minimum, p. 919); "
            f"{TYPICAL_NOTE}"
        )
        chw = water_flow(plan["unit"])
        pumps = []
        pl, pw, pwt = pump(chw)
        pumps += [_entry(f"CHWP{i + 1}", "pump", bottom, pl, pw, 1000, None, pwt) for i in range(n)]
        if plan["kind"] != "airCooled":
            rejected = heat_rejection(plan["unit"], plan["cop"])
            tl, tw, th, twt = _box("coolingTower", rejected)
            towers = [
                _entry(f"CT{i + 1}", "coolingTower", top, tl, tw, th, rejected, twt)
                for i in range(n)
            ]
            add("coolingTower", top, towers)
            notes.append(
                f"cooling towers reject Q (1 + 1/COP) = {plan['unit']:g} x (1 + 1/"
                f"{plan['cop']:g}) = {rejected:.0f} kW each; {TYPICAL_NOTE}"
            )
            cw = water_flow(rejected)
            cl, cwid, cwt = pump(cw)
            pumps += [
                _entry(f"CWP{i + 1}", "pump", bottom, cl, cwid, 1000, None, cwt) for i in range(n)
            ]
            main = pipe_size(cw * plan["duty"])
            pipes.append({"id": "CW-main", "service": "condenser water main (supply and return)",
                          "flow": cw * plan["duty"], **main, "count": 2,
                          "sleeve": pipe_sleeve(main["nominal"], 0.0)})  # fmt: skip
            if plan["unit"] * n >= INSTALLATION_500TR:
                height_need = 4500.0 if plan["kind"] == "centrifugal" else 3600.0
                checks.append(_headroom(project, bottom, height_need))
        add("pump", bottom, pumps)
        flows = f"chilled water {chw:.1f} l/s"
        if plan["kind"] != "airCooled":
            flows += f", condenser water {water_flow(rejected):.1f} l/s"
        notes.append(f"pumps, one per chiller: {flows} each at {WATER_DT:g} K; {TYPICAL_NOTE}")
        main = pipe_size(chw * plan["duty"])
        pipes.append({"id": "CHW-main", "service": "chilled water main (supply and return)",
                      "flow": chw * plan["duty"], **main, "count": 2,
                      "sleeve": pipe_sleeve(main["nominal"])})  # fmt: skip
        ahus = []
        for z in zones:
            if z["airflow"] <= 0:
                continue
            a = ahu_size(z["airflow"])
            ahus.append(_entry(bounded_id(f"AHU-{z['story']}"), "ahu", z["story"], a["length"],
                               a["width"], a["height"], z.get("total") or None, a["weight"],
                               serves=[z["story"]]))  # fmt: skip
        for unit in ahus:
            add("ahu", unit["story"], [unit])
        if ahus:
            notes.append(
                f"AHUs by a coil face velocity of {FACE_VELOCITY:g} m/s (SAEngine practice); "
                f"{TYPICAL_NOTE}"
            )
    elif system in ("vrf", "split", "packaged"):
        kind = {"vrf": "vrfOutdoor", "split": "splitOutdoor", "packaged": "packaged"}[system]
        n = max(1, math.ceil(q / UNIT_MAX[kind]))
        unit = math.ceil(q / n * 10 - 1e-6) / 10
        length, width, height, weight = _box(kind, unit)
        plant_kind = "ahu" if kind == "packaged" else kind
        prefix = {"vrfOutdoor": "ODU", "splitOutdoor": "SODU", "packaged": "PAC"}[kind]
        units = [
            _entry(f"{prefix}{i + 1}", plant_kind, top, length, width, height, unit, weight)
            for i in range(n)
        ]
        add(plant_kind, top, units)
        notes.append(f"{n} {kind} units of {unit:g} kW on {top}; {TYPICAL_NOTE}")
        if kind == "packaged":
            notes.append("packaged rooftop units are listed as kind 'ahu' (the contract has no "
                         "packaged kind)")  # fmt: skip
        if kind == "vrfOutdoor":
            per_system = min(q, 3 * UNIT_MAX["vrfOutdoor"])
            pair = refrigerant_pair(per_system)
            pipes.append({"id": "REF-pair", "service": "VRF refrigerant pipe pair (gas, liquid)",
                          "capacity": per_system, **pair, "count": math.ceil(n / 3),
                          "note": "typical size from manufacturers' piping tables: use the selected unit's"})  # fmt: skip
        if kind != "packaged":
            for z in zones:
                if z["outdoorAir"] <= 0:
                    continue
                a = ahu_size(z["outdoorAir"])
                add("freshAirUnit", z["story"], [_entry(
                    bounded_id(f"FAU-{z['story']}"), "freshAirUnit", z["story"], a["length"],
                    a["width"], a["height"], z["outdoorAir"], a["weight"],
                    serves=[z["story"]])])  # fmt: skip
    _exhaust_fans(project, all_zones, proposed, top, notes)
    classes = {"chiller": plan["kind"]} if system == "chilledWater" else {}
    if system == "packaged":
        classes["ahu"] = "packaged"
    plant = _merge(hvac.get("plant", []), proposed, notes, classes)
    from saengine.hvac.report import plant_equipment

    taken = {e.id for e in project.mep.equipment}
    equipment = [plant_equipment(p, taken) for p in plant]
    return {"plant": plant, "equipment": [e for e in equipment if e], "pipes": pipes,
            "capacity": cap, "checks": checks, "notes": notes}  # fmt: skip


def _exhaust_fans(
    project: Any, zones: list[dict[str, Any]], proposed: dict, top: str | None, notes: list[str]
) -> None:
    """A roof exhaust fan at the top of each exhaust and kitchen exhaust riser that reaches
    the top story, sized by the riser's airflow (:func:`saengine.hvac.air.duct_flows`)."""
    if top is None:
        return
    from saengine.hvac.air import duct_flows

    flows, _ = duct_flows(project, zones)
    for duct in project.hvac.get("ducts", []):
        riser = duct.get("riser")
        if not riser or duct.get("system") not in ("exhaust", "kitchenExhaust", "smoke"):
            continue
        if riser.get("toStory") != top or not duct.get("path"):
            continue
        flow = flows.get(duct["id"]) or 0.0
        x, y = duct["path"][0][:2]
        fan = _entry(bounded_id(f"EF-{duct['id']}"), "exhaustFan", top, 1200, 1200, 1000,
                     flow, FAN_BASE + FAN_PER * flow)  # fmt: skip
        fan["x"], fan["y"] = float(x), float(y)
        proposed.setdefault("exhaustFan", []).append(fan)
    if proposed.get("exhaustFan"):
        notes.append(f"roof exhaust fans at the top of the exhaust risers; {TYPICAL_NOTE}")


def own_size(
    kind: str | None, capacity: float, cls: str | None = None
) -> tuple[float, float, float, float] | None:
    """TYPICAL (length, width, height [mm], operating weight [kN]) of a plant unit of the given
    ``capacity`` (kW cooling; kW rejected for a cooling tower; m³/s for fans and fresh-air
    units): what an engineer-placed unit without them weighs. ``cls``: the chiller class
    (``airCooled`` keeps it air-cooled up to 1400 kW a unit; a water-cooled one is screw up to
    1050 kW, centrifugal above) or ``"packaged"`` for a packaged rooftop unit listed as an AHU. None for pumps (the
    capacity gives no flow)."""
    if capacity is None or capacity <= 0:
        return None
    if kind == "chiller":
        if cls != "airCooled" or capacity > UNIT_MAX["airCooled"]:
            cls = "screw" if capacity <= UNIT_MAX["screw"] else "centrifugal"
        return _box(cls, capacity)
    if kind in ("coolingTower", "vrfOutdoor", "splitOutdoor"):
        return _box(kind, capacity)
    if kind == "ahu" and cls == "packaged":
        return _box("packaged", capacity)
    if kind == "ahu":
        from saengine.hvac.air import CP, RHO, SUPPLY_DT

        # Total kW as if sensible: more air than it needs, on the heavy side.
        a = ahu_size(capacity / (RHO * CP * SUPPLY_DT))
        return a["length"], a["width"], a["height"], a["weight"]
    if kind == "freshAirUnit":
        a = ahu_size(capacity)
        return a["length"], a["width"], a["height"], a["weight"]
    if kind == "exhaustFan":
        return 1200.0, 1200.0, 1000.0, FAN_BASE + FAN_PER * capacity
    return None


def _merge(
    existing: list[dict[str, Any]],
    proposed: dict[str, list[dict[str, Any]]],
    notes: list[str],
    classes: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """The engineer's own (not ``sized``) plant of a kind replaces SAEngine's of that kind,
    completed where it gives none with the TYPICAL size and weight of a unit of its own
    capacity (:func:`own_size`), or of SAEngine's proposed unit when it gives no capacity;
    SAEngine's earlier proposals (``sized``) are replaced."""
    classes = classes or {}
    own: dict[str, list[dict[str, Any]]] = {}
    for p in existing:
        if not p.get("sized"):
            own.setdefault(p.get("kind"), []).append(p)
    out: list[dict[str, Any]] = []
    keys = ("length", "width", "height", "operatingWeight")
    for kind, units in proposed.items():
        if kind not in own:
            out.extend(units)
            continue
        template = units[0]
        for p in own[kind]:
            entry = dict(p)
            capacity = entry.get("capacity")
            sized = own_size(kind, float(capacity), classes.get(kind)) if capacity else None
            if sized is not None:
                unit = "m³/s" if kind in ("exhaustFan", "freshAirUnit") else "kW"
                source = f"a typical {kind} of its own {float(capacity):g} {unit}"
                values = dict(zip(keys, (*sized[:3], round(sized[3], 1)), strict=True))
            else:
                if capacity is None:
                    entry["capacity"] = template["capacity"]
                source = "SAEngine's proposed unit"
                values = {k: template[k] for k in keys}
            missing = [k for k in keys if entry.get(k) is None]
            for key in missing:
                entry[key] = values[key]
            if missing:
                notes.append(
                    f"{entry.get('id')}: {', '.join(missing)} from {source} ({TYPICAL_NOTE})"
                )
            out.append(entry)
        notes.append(
            f"{len(own[kind])} {kind} given in 07 MEP kept (SAEngine proposed {len(units)})"
        )
    for kind, units in own.items():
        if kind not in proposed:
            out.extend(dict(u) for u in units)
    return out


def _headroom(project: Any, story: str | None, need: float) -> dict[str, Any]:
    """BNBC Sec 2.6.2.4(b): clear headroom below beam soffits of a chiller plant room."""
    height = project.story_height(story) if story else None
    clear = (height or 0.0) - _deepest_beam(project, project.above(story) if story else None)
    return {
        "name": f"Chiller plant room headroom ({story})", "demand": need, "capacity": clear,
        "unit": "mm", "utilisation": need / clear if clear > 0 else math.inf,
        "ok": clear >= need,
        "note": "below the beam soffit, BNBC 2020 Part 8 Sec 2.6.2.4(b) (p. 853), water-cooled "
        "chiller installations of 500 TR and above: 4.5 m centrifugal, 3.6 m "
        "screw/reciprocating",
    }  # fmt: skip


def _deepest_beam(project: Any, story: str | None) -> float:
    """Depth [mm] of the deepest beam at a story's level (0 without 06 BIM)."""
    if story is None or project.bim is None or project.objects is None:
        return 0.0
    from saengine.library.bim import BeamElement
    from saengine.mep.clash import _depth

    level = project.building.stories.get(story)
    types = {o.id: o for o in project.objects.objects}
    depth = 0.0
    for e in project.bim.elements:
        if isinstance(e, BeamElement) and level is not None and abs(e.elevation - level) < 300:
            depth = max(depth, _depth(getattr(types.get(e.type), "profile", None)))
    return depth


def coincident_peak(loads: dict[str, Any] | None) -> float | None:
    """The coincident cooling peak of all zones [kW] the load calculation gives (EnergyPlus's
    ``building.total``), or None."""
    building = (loads or {}).get("building")
    value = building.get("total") if isinstance(building, dict) else None
    return float(value) if isinstance(value, int | float) and value > 0 else None


def hvac_propose_plant(
    project_root: Any, loads: dict[str, Any] | None = None, mep_text: str | None = None
) -> dict[str, Any]:
    """The proposed plant of a project (see :func:`propose_plant`); ``loads``: the HVAC load
    calculation's result (None runs it)."""
    from saengine.hvac.air import _hvac_loads, load_project, zone_air

    project = load_project(project_root, mep_text)
    if loads is None:
        loads = _hvac_loads(project_root, mep_text)
    zones, notes = zone_air(project, loads)
    result = propose_plant(project, zones, coincident=coincident_peak(loads))
    result["notes"] = notes + result["notes"]
    result["problems"] = project.problems
    return result

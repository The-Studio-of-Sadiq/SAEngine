"""HVAC air distribution for the structure's coordination: airflows, duct sizes, shafts.

What the structural engineer needs of the air side is the space the ducts take (the openings
they need through beams and slabs, the shafts their risers need) and the plant the airflows
size (:mod:`saengine.hvac.plant`). This module works the airflows and duct sizes out:

- Supply air of a zone from its sensible load: Q = qs / (rho cp dT) with standard air
  (rho = 1.2 kg/m³, cp = 1.005 kJ/kg K) and a supply temperature difference ``dT`` of 10 K
  unless given (SAEngine practice: a room at 24-25 °C supplied at 14-15 °C; BNBC 2020 Part 8
  Ch 2 gives no supply temperature). The airflow of the load calculation is used when it
  gives one.
- Outdoor air: BNBC 2020 Part 8 Table 8.2.3 (Minimum Ventilation Rates for Air Conditioned
  Spaces, pp. 863-869 of the Part 2 volume, as :mod:`saengine.hvac.tables` transcribes it;
  ``hvac.stories[].use`` is its row key): the breathing-zone rates per person Rp and per
  m² Ra and the default occupant density. The two rates are added, Vbz = Rp Pz + Ra Az (the
  ASHRAE 62.1 ventilation rate procedure the table comes from; BNBC gives the columns, not
  the sum), and never less than 2.5 l/s per person (BNBC 2020 Part 8 Sec 2.11.3.4, p. 905).
  Dwellings: 0.35 air changes per hour but not less than 7.5 l/s per person (Table 8.2.3,
  "Living areas", p. 866).
- Exhaust: Table 8.2.3's exhaust rates: public toilets 25 l/s per water closet or urinal
  (30 for heavy use, note e, p. 867/869), private toilets and bathrooms 10 l/s per room
  (continuous; 25 intermittent, note f, p. 866), hotel bathrooms 12.5 l/s per room (p. 865),
  dwelling kitchens 12.5 l/s per kitchen (continuous; 50 intermittent, p. 866), commercial
  kitchens 3.5 l/s per m² (p. 865), enclosed parking 3.75 l/s per m² (p. 868). The toilets
  and kitchens are counted from 07 MEP's plumbing fixtures (water closets, urinals, kitchen
  sinks) of the story.
- Ducts: galvanised steel, Darcy-Weisbach with the Colebrook friction factor (``fluids``,
  MIT, Clamond's solution), absolute roughness 0.09 mm (ASHRAE Handbook Fundamentals Ch 21,
  galvanised steel: from memory, to be checked). Sized by the equal-friction method at
  1.0 Pa/m unless given, and by a maximum velocity: BNBC 2020 Part 8 Ch 2 gives no duct
  velocity table; it sets 7.62 to 12.7 m/s in kitchen exhaust ducts (Sec 2.11.5.1(d),
  p. 912) and requires linings exposed to more than 10 m/s to be fastened mechanically
  (Sec 2.8.1.5(b), p. 873). The other limits are SAEngine defaults for low-velocity
  commercial systems after the ASHRAE Handbook (supply 7.5, return and exhaust 6.0, fresh
  air 5.0, smoke 10 m/s: from memory, to be checked). The larger of the two sizes governs.
- Rectangles: the equivalent diameter of Huebscher, De = 1.30 (a b)^0.625 / (a + b)^0.25
  (ASHRAE Handbook Fundamentals Ch 21), sides in 50 mm steps from 100 mm, aspect ratio at
  most 4:1 (SAEngine practice); the shallowest rectangle that works is chosen, as the depth
  is what the structure has to make room for.
- Shafts: each duct in a shaft takes its outside size (with its insulation) plus 75 mm all
  round (SAEngine practice, BNBC Sec 2.11.5.1(f)'s least clearance of a kitchen exhaust
  duct to its enclosure, p. 912, applied to all ducts); the pipes of 07 MEP's plumbing risers
  with a given diameter take (OD + 100 mm)² as the plumbing shaft check counts them.

The 07 MEP ``hvac`` section is read as plain JSON (``hvac`` of the contract), so this module
works with or without its pydantic model.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shapely.geometry import Point, Polygon

from saengine.library.mep import MEP_FILE, MepModel, parse
from saengine.plumbing.building import Building

# ─────────────────────────────────────── constants ───────────────────────────────────────

RHO = 1.2  # kg/m³, standard air
CP = 1.005  # kJ/(kg K)
MU = 1.81e-5  # Pa s, air at 20 °C
ROUGHNESS = 0.09  # mm, galvanised steel (ASHRAE Fundamentals Ch 21; from memory)
SUPPLY_DT = 10.0  # K, SAEngine practice
FRICTION_RATE = 1.0  # Pa/m, equal friction
ASPECT_MAX = 4.0
STEP = 50.0  # mm
MIN_SIDE = 100.0  # mm
MIN_PER_PERSON = 2.5  # l/s, BNBC 2020 Part 8 Sec 2.11.3.4
#: Insulation thickness [mm] by duct system: BNBC 2020 Part 8 Sec 2.8.1.5(a) requires supply
#: and return ducts of a cooling system to be insulated; 25 mm is SAEngine's default.
INSULATION = {"supply": 25.0, "return": 25.0, "freshAir": 25.0}
SHAFT_CLEARANCE = 75.0  # mm all round a duct in a shaft (SAEngine practice)

SYSTEMS = ("supply", "return", "exhaust", "freshAir", "kitchenExhaust", "smoke")
#: (minimum, maximum) velocity [m/s] and where it comes from.
VELOCITY = {
    "supply": (
        None,
        7.5,
        "SAEngine default (typical low-velocity duct practice, ASHRAE Handbook Fundamentals Ch 21; set the project's limit)",
    ),
    "return": (
        None,
        6.0,
        "SAEngine default (typical low-velocity duct practice, ASHRAE Handbook Fundamentals Ch 21; set the project's limit)",
    ),
    "exhaust": (
        None,
        6.0,
        "SAEngine default (typical low-velocity duct practice, ASHRAE Handbook Fundamentals Ch 21; set the project's limit)",
    ),
    "freshAir": (
        None,
        5.0,
        "SAEngine default (typical low-velocity duct practice, ASHRAE Handbook Fundamentals Ch 21; set the project's limit)",
    ),
    "kitchenExhaust": (7.62, 12.7, "BNBC 2020 Part 8 Sec 2.11.5.1(d), p. 912"),
    "smoke": (None, 10.0, "SAEngine default (set the smoke control design's limit)"),
}
TABLE_823 = "BNBC 2020 Part 8 Table 8.2.3"


#: Exhaust per fixture or room [l/s] of Table 8.2.3: (continuous/normal, intermittent/heavy).
TOILET_PUBLIC = (25.0, 30.0)  # per water closet or urinal, note e (p. 867)
TOILET_PRIVATE = (10.0, 25.0)  # per room, dwellings, note f (p. 866)
TOILET_HOTEL = (12.5, 25.0)  # per room, hotels (p. 865)
KITCHEN_PRIVATE = (12.5, 50.0)  # per kitchen, dwellings (p. 866)
#: BNBC 2020 Part 8 Table 8.2.8 (Part 2 volume p. 914): design exhaust air flow [l/s per kW of
#: the kitchen equipment], (electricity based, gas based; None: not given). Sec 2.11.5.1(g)
#: (p. 912): commercial kitchen exhaust is calculated from it.
TABLE_828 = {
    "cookingPot": (8.0, 12.0),
    "pressureCookerCabinet": (5.0, None),
    "convectionOven": (10.0, None),
    "roastingOven": (33.0, 33.0),
    "griddle": (32.0, 35.0),
    "fryingPan": (32.0, 35.0),
    "deepFatFryer": (28.0, None),
    "cookerStove": (32.0, 35.0),
    "grill": (50.0, 61.0),
    "heatedTable": (30.0, None),
    "coffeemaker": (3.0, None),
    "dishWasher": (17.0, None),
    "refrigeration": (60.0, None),
    "ceramicCookerStove": (25.0, None),
    "microwaveOven": (3.0, None),
    "pizzaOven": (15.0, None),
    "inductionCookerStove": (20.0, None),
}
#: Rate [l/s per kW] for a kitchen whose equipment is given only as a total (the story's
#: ``equipment`` W/m²): Table 8.2.8's cooker/stove, gas (SAEngine choice for an unknown mix).
KITCHEN_RATE_DEFAULT = TABLE_828["cookerStove"][1]
TABLE_828_SOURCE = "BNBC 2020 Part 8 Sec 2.11.5.1(g) and Table 8.2.8 (pp. 912, 914)"
DEFAULT_USE = "officeSpace"
#: Table 8.2.3's page of each group of rows (Part 2 volume).
GROUP_PAGE = {
    "correctional": 863, "laundry": 864, "education": 864, "food": 865, "hospital": 865,
    "hotel": 865, "office": 866, "dwelling": 866, "public": 866, "retail": 867,
    "specialty": 867, "sports": 868, "storage": 868, "theater": 868, "transport": 868,
    "workroom": 869,
}  # fmt: skip

#: BNBC 2020 Part 3 Table 3.1.9 (Part 1 volume p. 66), air-conditioned buildings [mm], by the
#: Table 8.2.3 group (educational, institutional, health care, assembly; storage); the others
#: take Sec 1.14.2.1(b)'s 2.44 m under a duct.
CEILING_TABLE_319 = {
    **dict.fromkeys(("education", "hospital", "correctional", "theater"), 2600.0),
    "storage": 3000.0,
}
ASSEMBLY_USES = ("worship", "courtroom", "legislative", "spectator", "hotelAssembly")
HEADROOM_UNDER_DUCT = 2440.0  # mm, BNBC 2020 Part 3 Sec 1.14.2.1(b)


def ventilation_row(use: str | None) -> tuple[Any, str]:
    """The Table 8.2.3 row of a use (stream H1's :data:`saengine.hvac.tables.VENTILATION`),
    and a note when the use is not in it (office spaces are taken)."""
    from saengine.hvac.tables import VENTILATION

    row = VENTILATION.get(use or "")
    if row is None:
        return VENTILATION[DEFAULT_USE], f"use '{use}' is not in Table 8.2.3: office spaces taken"
    return row, ""


def ceiling_height(use: str | None) -> float | None:
    """Table 3.1.9's air-conditioned ceiling height of a use [mm] (None: Sec 1.14.2.1)."""
    if use in ASSEMBLY_USES:
        return 2600.0
    from saengine.hvac.tables import VENTILATION

    row = VENTILATION.get(use or "")
    return CEILING_TABLE_319.get(row.group) if row else None


# ─────────────────────────────────────── airflows ───────────────────────────────────────


def supply_airflow(sensible_kw: float, dt: float = SUPPLY_DT) -> float:
    """Supply airflow [m³/s] that takes away ``sensible_kw`` with a supply ``dt`` [K]."""
    if dt <= 0:
        raise ValueError("the supply temperature difference must be positive")
    return max(sensible_kw, 0.0) / (RHO * CP * dt)


def outdoor_air(
    use: str | None,
    area: float,
    occupants: float | None = None,
    height: float | None = None,
) -> dict[str, Any]:
    """Outdoor air [m³/s] of a zone of ``area`` m² (Table 8.2.3): ``{"flow", "occupants",
    "perPerson", "perArea", "source", "note"}``. ``height``: room height [m] (dwellings)."""
    row, note = ventilation_row(use)
    source = f"{TABLE_823}, {row.label} (p. {GROUP_PAGE.get(row.group, 863)})"
    if row.ach:
        volume = area * (height or 3.0)
        by_ach = row.ach * volume / 3600.0
        people = occupants or 0.0
        by_people = (row.perPerson or 0.0) * people / 1000.0
        if not occupants:
            note = "dwelling occupants not given (the table counts 2 for the first bedroom and "
            "1 for each other): the air changes only"
        return {
            "flow": max(by_ach, by_people), "occupants": people, "perPerson": row.perPerson,
            "perArea": None, "source": f"{source}: {row.ach:g} ACH, at least "
            f"{row.perPerson:g} l/s per person", "note": note,
        }  # fmt: skip
    if occupants is None:
        occupants = (row.density or 0.0) * area / 100.0
    rp = row.perPerson or 0.0
    ra = row.perArea or 0.0
    flow = rp * occupants + ra * area
    flow = max(flow, MIN_PER_PERSON * occupants)
    return {
        "flow": flow / 1000.0,
        "occupants": occupants,
        "perPerson": row.perPerson,
        "perArea": row.perArea,
        "source": source + "; at least 2.5 l/s per person (Sec 2.11.3.4)",
        "note": note,
    }


def kitchen_exhaust_flow(items: list[tuple[str, float, str]]) -> float:
    """Commercial kitchen exhaust [m³/s] of its equipment (BNBC Table 8.2.8): ``items`` are
    (Table 8.2.8 key of :data:`TABLE_828`, rating kW, ``"electric"`` or ``"gas"``)."""
    total = 0.0
    for key, kw, fuel in items:
        electric, gas = TABLE_828[key]
        rate = gas if fuel == "gas" else electric
        if rate is None:
            raise ValueError(f"Table 8.2.8 gives no {fuel} rate for {key}")
        total += rate * kw
    return total / 1000.0


def story_exhaust(
    use: str | None,
    area: float,
    fixtures: Any = None,
    heavy: bool = False,
    kitchen_kw: float | None = None,
) -> dict[str, Any]:
    """Toilet and kitchen exhaust [m³/s] of a story from its plumbing fixtures and use (Table
    8.2.3): ``{"toilet", "kitchen", "general", "notes"}``. Dwellings (Table 8.2.3 group
    "dwelling"): 10 l/s per bathroom (one per water closet) and 12.5 l/s per kitchen (one per
    kitchen sink); hotels: 12.5 l/s per bathroom; others: 25 l/s per water closet or urinal
    (the continuous or normal rates; ``heavy``: the intermittent or heavy-use ones).
    Commercial kitchens (``kitchenCooking``): Table 8.2.8 (Sec 2.11.5.1(g)) at
    :data:`KITCHEN_RATE_DEFAULT` l/s per kW of ``kitchen_kw``, the kitchen's equipment rating;
    without it Table 8.2.3's 3.5 l/s per m² stands in and ``kitchenBasis`` says so."""
    row, _ = ventilation_row(use)
    k = 1 if heavy else 0
    wc = int(getattr(fixtures, "wc", 0) or 0)
    urinal = int(getattr(fixtures, "urinal", 0) or 0)
    sinks = int(getattr(fixtures, "kitchenSink", 0) or 0)
    notes = []
    kitchen = 0.0
    if row.group == "dwelling":
        toilet = TOILET_PRIVATE[k] * wc
        kitchen = KITCHEN_PRIVATE[k] * sinks
        notes.append(
            f"{wc} bathrooms x {TOILET_PRIVATE[k]:g} l/s and {sinks} kitchens x "
            f"{KITCHEN_PRIVATE[k]:g} l/s ({TABLE_823}, private dwellings, p. 866)"
        )
    elif row.group == "hotel":
        toilet = TOILET_HOTEL[k] * wc
        notes.append(f"{wc} bathrooms x {TOILET_HOTEL[k]:g} l/s ({TABLE_823}, hotels, p. 865)")
    else:
        toilet = TOILET_PUBLIC[k] * (wc + urinal)
        notes.append(
            f"{wc + urinal} water closets and urinals x {TOILET_PUBLIC[k]:g} l/s "
            f"({TABLE_823}, public toilets, p. 867)"
        )
    general = (row.exhaust or 0.0) * area if row.exhaust and not row.exhaustNote else 0.0
    basis = None
    if row.key == "kitchenCooking":
        if kitchen_kw:
            kitchen += KITCHEN_RATE_DEFAULT * kitchen_kw
            basis = "table828"
            notes.append(
                f"kitchen exhaust {kitchen_kw:g} kW of equipment x {KITCHEN_RATE_DEFAULT:g} l/s "
                f"per kW (cooker/stove, gas: SAEngine choice for an unknown mix; "
                f"{TABLE_828_SOURCE})"
            )
        else:
            kitchen += general
            basis = "table823"
            notes.append(
                f"kitchen exhaust {row.exhaust:g} l/s per m² ({TABLE_823}, p. 865) in place of "
                f"{TABLE_828_SOURCE}: give the kitchen's equipment [W/m²] on its hvac story, or "
                "the duct's flow"
            )
        general = 0.0
    return {"toilet": toilet / 1000, "kitchen": kitchen / 1000, "general": general / 1000,
            "kitchenBasis": basis, "notes": notes}  # fmt: skip


# ─────────────────────────────────────── ducts ───────────────────────────────────────


def friction_gradient(flow: float, diameter: float) -> float:
    """Pressure loss [Pa/m] of ``flow`` m³/s in a round duct of ``diameter`` mm (Darcy-Weisbach
    with the Colebrook friction factor of ``fluids``)."""
    from fluids.friction import friction_factor

    d = diameter / 1000.0
    v = flow / (math.pi * d * d / 4)
    re = RHO * v * d / MU
    f = friction_factor(Re=re, eD=ROUGHNESS / diameter)
    return f / d * RHO * v * v / 2


def round_for_friction(flow: float, rate: float = FRICTION_RATE) -> float:
    """Round duct diameter [mm] at which ``flow`` loses ``rate`` Pa/m (equal friction)."""
    from scipy.optimize import brentq

    return float(brentq(lambda d: friction_gradient(flow, d) - rate, 10.0, 10000.0, xtol=0.01))


def equivalent_diameter(width: float, height: float) -> float:
    """Huebscher's circular equivalent [mm] of a ``width`` x ``height`` rectangle (same friction
    and flow)."""
    return 1.30 * (width * height) ** 0.625 / (width + height) ** 0.25


def _up(value: float, step: float = STEP, least: float = MIN_SIDE) -> float:
    return max(least, math.ceil(value / step - 1e-9) * step)


def size_duct(
    flow: float,
    system: str = "supply",
    shape: str = "rect",
    rate: float = FRICTION_RATE,
    max_height: float | None = None,
) -> dict[str, Any]:
    """The duct for ``flow`` m³/s of ``system``: by equal friction at ``rate`` Pa/m and by the
    velocity limits; a rectangle no deeper than ``max_height`` mm when it can be.
    ``{"shape", "width", "height" | "diameter", "velocity", "friction", "governs", "ok",
    "note", "frictionDiameter", "velocityDiameter"}``."""
    if flow <= 0:
        raise ValueError("a duct needs a positive airflow")
    vmin, vmax, vsource = VELOCITY.get(system, VELOCITY["supply"])
    area_v = flow / vmax * 1e6  # mm²
    d_v = math.sqrt(4 * area_v / math.pi)
    by_velocity = system == "kitchenExhaust"  # BNBC's velocity range governs, not friction
    d_f = 0.0 if by_velocity else round_for_friction(flow, rate)
    governs = "velocity" if d_v >= d_f else "friction"
    need_d = max(d_f, d_v)
    notes = [f"velocity limit {vmax:g} m/s ({vsource})"]
    if not by_velocity:
        notes.append(f"equal friction {rate:g} Pa/m (SAEngine default)")
    if shape == "round":
        d = _up(need_d)
        result = {"shape": "round", "diameter": d}
        area, de = math.pi * d * d / 4, d
    else:
        w, h = _rectangle(d_f, area_v, max_height)
        if w is None:
            w, h = _rectangle(d_f, area_v, None)
            notes.append(f"no duct of aspect ratio up to {ASPECT_MAX:g} fits {max_height:g} mm")
        result = {"shape": "rect", "width": w, "height": h}
        area, de = w * h, equivalent_diameter(w, h)
    velocity = flow / (area / 1e6)
    ok = velocity <= vmax + 1e-9 and (vmin is None or velocity >= vmin - 1e-9)
    if vmin is not None and velocity < vmin:
        notes.append(f"{velocity:.2f} m/s is below the {vmin:g} m/s minimum")
    return {
        **result,
        "velocity": velocity,
        "friction": friction_gradient(flow, de),
        "governs": governs,
        "frictionDiameter": d_f,
        "velocityDiameter": d_v,
        "ok": ok,
        "note": "; ".join(notes),
    }


def _rectangle(
    d_need: float, area_need: float, max_height: float | None
) -> tuple[float | None, float | None]:
    """The shallowest rectangle (50 mm steps, aspect at most 4) whose equivalent diameter is at
    least ``d_need`` and area at least ``area_need`` mm²; (None, None) when none is shallow
    enough."""
    top = max_height if max_height is not None else 5000.0
    h = MIN_SIDE
    while h <= top + 1e-9:
        w = h
        while w <= ASPECT_MAX * h + 1e-9:
            if w * h >= area_need - 1e-6 and equivalent_diameter(w, h) >= d_need - 1e-6:
                return w, h
            w += STEP
        h += STEP
    return None, None


def check_duct(flow: float, size: dict[str, Any], system: str = "supply") -> dict[str, Any]:
    """Velocity [m/s] and friction [Pa/m] of ``flow`` in a given duct, against the limits."""
    vmin, vmax, vsource = VELOCITY.get(system, VELOCITY["supply"])
    if size.get("shape") == "round" or size.get("diameter"):
        d = float(size["diameter"])
        area, de = math.pi * d * d / 4, d
    else:
        w, h = float(size["width"]), float(size["height"])
        area, de = w * h, equivalent_diameter(w, h)
    velocity = flow / (area / 1e6)
    ok = velocity <= vmax + 1e-9 and (vmin is None or velocity >= vmin - 1e-9)
    return {"velocity": velocity, "friction": friction_gradient(flow, de), "ok": ok,
            "limit": vmax, "minimum": vmin, "note": vsource}  # fmt: skip


def outside(duct: dict[str, Any], size: dict[str, Any] | None = None) -> tuple[float, float, bool]:
    """Outside (insulated) width and height [mm] of a duct and whether it is round."""
    size = size or duct
    insulation = INSULATION.get(duct.get("system", "supply"), 0.0)
    if size.get("shape") == "round" or (size.get("diameter") and not size.get("width")):
        d = float(size["diameter"]) + 2 * insulation
        return d, d, True
    return (
        float(size["width"]) + 2 * insulation,
        float(size["height"]) + 2 * insulation,
        False,
    )


# ─────────────────────────────────────── the project ───────────────────────────────────────


@dataclass
class Project:
    """What the HVAC coordination reads of a project."""

    root: Path
    mep: MepModel
    hvac: dict[str, Any]
    bim: Any = None
    objects: Any = None
    materials: Any = None
    building: Building = field(default_factory=Building)
    problems: list[str] = field(default_factory=list)

    @property
    def order(self) -> list[str]:
        if self.building.known:
            return self.building.ordered()
        return [s.get("story") for s in self.hvac.get("stories", [])]

    def story_height(self, story: str) -> float | None:
        """Floor to floor [mm] (None for the top story or unknown levels)."""
        order = self.order
        if story not in order or not self.building.known:
            return None
        i = order.index(story)
        if i + 1 >= len(order):
            return None
        return self.building.stories[order[i + 1]] - self.building.stories[story]

    def above(self, story: str) -> str | None:
        order = self.order
        if story not in order:
            return None
        i = order.index(story)
        return order[i + 1] if i + 1 < len(order) else None


def _read(root: Path, relative: str) -> str | None:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError:
        return None


def hvac_section(mep: MepModel, data: dict[str, Any] | None) -> dict[str, Any]:
    """The ``hvac`` section as plain JSON: from the model when it has one, else the file's."""
    model = getattr(mep, "hvac", None)
    if model is not None and hasattr(model, "model_dump"):
        return model.model_dump(mode="json", exclude_none=True, by_alias=True)
    return dict((data or {}).get("hvac") or {})


def load_project(project_root: str | Path, mep_text: str | None = None) -> Project:
    """07 MEP (with its ``hvac``), 06 BIM, 04 Objects and 03 Materials of a project. Raises
    ``ValueError`` when 07 MEP cannot be read; the others are optional (``problems``)."""
    from saengine.library.bim import BuildingModel
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary

    root = Path(project_root)
    text = mep_text if mep_text is not None else _read(root, MEP_FILE)
    data: dict[str, Any] = {}
    if text and text.strip():
        try:
            data = json.loads(text)
        except ValueError as error:
            raise ValueError(f"{MEP_FILE} is not valid: {error}") from error
    try:
        mep = parse(text)
    except ValueError as error:
        # Before the hvac/electrical models are in library/mep.py: parse the rest.
        rest = {k: v for k, v in data.items() if k not in ("hvac", "electrical")}
        if rest == data:
            raise ValueError(f"{MEP_FILE} is not valid: {error}") from error
        mep = parse(json.dumps(rest))
    project = Project(root, mep, hvac_section(mep, data))
    for relative, attribute, kind in (
        ("06 BIM/bim.json", "bim", BuildingModel),
        ("04 Objects/objects.json", "objects", ObjectLibrary),
        ("03 Materials/materials.json", "materials", MaterialLibrary),
    ):
        raw = _read(root, relative)
        if not raw:
            continue
        try:
            setattr(project, attribute, kind.model_validate_json(raw))
        except ValueError as error:
            project.problems.append(f"{relative} is not valid: {error}")
    project.building = Building.of(project.bim)
    return project


def _hvac_loads(project_root: str | Path, mep_text: str | None) -> dict[str, Any] | None:
    """The zone loads of the HVAC load calculation (:func:`saengine.hvac.report.hvac_loads`):
    its cached EnergyPlus run when it matches the input, else the estimate (EnergyPlus is only
    started by Calculate Loads); None when it is missing."""
    try:
        from saengine.hvac.report import hvac_loads  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        return hvac_loads(project_root, mep_text=mep_text, run_energyplus=False)
    except TypeError:
        return hvac_loads(project_root)


def _zone_items(loads: dict[str, Any] | None, project: Project) -> list[tuple[str, dict]]:
    """(story, zone) of the load calculation's zones: a list of zones with their ``story``, or
    EnergyPlus's mapping of zone names (the story id, any case) to zones."""
    zones = (loads or {}).get("zones") or []
    if isinstance(zones, dict):
        by_upper = {s.upper(): s for s in project.order if s}
        items = []
        for name, zone in zones.items():
            story = zone.get("story") or by_upper.get(str(name).upper(), str(name))
            items.append((story, zone))
        return items
    return [(z.get("story"), z) for z in zones if isinstance(z, dict)]


def _floor_area(project: Project, story: str) -> float:
    """Plan area of a story's slabs [m²], else of the story above's (a floor on grade)."""
    area = project.building.floor_area(story)
    above = project.above(story)
    if area <= 0 and above:
        area = project.building.floor_area(above)
    return area


def _num(zone: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = zone.get(key)
        if isinstance(value, int | float) and math.isfinite(value):
            return float(value)
    return None


# ─────────────────────────────────────── zones ───────────────────────────────────────


def zone_air(
    project: Project, loads: dict[str, Any] | None, dt: float = SUPPLY_DT
) -> tuple[list[dict[str, Any]], list[str]]:
    """Supply and outdoor air of each zone of ``loads`` (H1's ``{"zones": [{"story",
    "sensible" kW, "total", "latent", "airflow" m³/s?, "area" m²?, "occupants"?,
    "outdoorAir" m³/s?}]}``) and the exhaust of each story."""
    notes: list[str] = []
    entries = {s.get("story"): s for s in project.hvac.get("stories", [])}
    plumbing = {s.story: s for s in (project.mep.plumbing.stories if project.mep.plumbing else [])}
    zones = []
    for story, zone in _zone_items(loads, project):
        if zone.get("problem"):
            notes.append(f"{story}: {zone['problem']}")
            continue
        entry = entries.get(story, {})
        use = entry.get("use") or zone.get("use")
        area = _num(zone, "area", "floorArea") or _floor_area(project, story)
        sensible = _num(zone, "sensible", "sensibleKw") or 0.0
        airflow = _num(zone, "airflow", "supplyAir")
        source = "the load calculation's airflow"
        if airflow is None:
            airflow = supply_airflow(sensible, dt)
            source = (
                f"qs / (rho cp dT) = {sensible:.2f} / (1.2 x 1.005 x {dt:g}) (SAEngine practice dT)"
            )
        occupants = entry.get("occupants", zone.get("occupants"))
        height = project.story_height(story)
        oa = outdoor_air(use, area, occupants, height / 1000 if height else None)
        given_oa = _num(zone, "outdoorAir")
        if given_oa is None and isinstance(zone.get("ventilation"), dict):
            given_oa = _num(zone["ventilation"], "flow")
        outdoor = given_oa if given_oa is not None else oa["flow"]
        fixtures = plumbing[story].fixtures if story in plumbing else None
        exhaust = story_exhaust(use, area, fixtures, kitchen_kw=_kitchen_kw(entry, area))
        supply = max(airflow, outdoor)
        zone_notes = [n for n in (oa["note"],) if n]
        if supply > airflow + 1e-9:
            zone_notes.append("supply raised to the outdoor air")
        zones.append({
            "story": story, "use": use, "area": area, "sensible": sensible,
            "total": _num(zone, "total", "totalKw"), "airflow": supply,
            "airflowSource": source, "outdoorAir": outdoor, "outdoorAirSource": oa["source"]
            if given_oa is None else "the load calculation", "occupants": oa["occupants"],
            "exhaust": exhaust, "notes": zone_notes, "conditioned": True,
        })  # fmt: skip
    if not zones:
        notes.append("no zone loads: run the HVAC load calculation first")
    zones += _unconditioned(project, {z["story"] for z in zones}, entries, plumbing, notes)
    return zones, notes


def _kitchen_kw(entry: dict[str, Any], area: float) -> float | None:
    """A commercial kitchen's equipment rating [kW]: its story's ``equipment`` W/m² given."""
    if entry.get("use") != "kitchenCooking" or not entry.get("equipment"):
        return None
    return float(entry["equipment"]) * area / 1000.0


def _unconditioned(
    project: Project,
    done: set[str],
    entries: dict[str, dict[str, Any]],
    plumbing: dict[str, Any],
    notes: list[str],
) -> list[dict[str, Any]]:
    """Ventilation-only zones of the stories the load calculation leaves out because they are
    not conditioned (an hvac story with ``conditioned: false``; with hvac stories listed, a
    story without one, as H1's zoning takes it): their toilet, kitchen and general exhaust
    (enclosed parking, Table 8.2.3), no supply or outdoor air (make-up air not worked out)."""
    stories = [s for s, e in entries.items() if s and e.get("conditioned") is False]
    if entries:
        stories += [s for s in project.order if s and s not in entries]
    out = []
    for story in dict.fromkeys(stories):
        if story in done:
            continue
        entry = entries.get(story, {})
        use = entry.get("use")
        area = _floor_area(project, story)
        fixtures = plumbing[story].fixtures if story in plumbing else None
        if area <= 0 and fixtures is None:
            continue
        exhaust = story_exhaust(use, area, fixtures, kitchen_kw=_kitchen_kw(entry, area))
        if not (exhaust["toilet"] or exhaust["kitchen"] or exhaust["general"]):
            continue
        out.append({
            "story": story, "use": use, "area": area, "sensible": 0.0, "total": None,
            "airflow": 0.0, "airflowSource": "not conditioned", "outdoorAir": 0.0,
            "outdoorAirSource": "not conditioned (make-up air not worked out)",
            "occupants": None, "exhaust": exhaust, "notes": ["not conditioned: exhaust only"],
            "conditioned": False,
        })  # fmt: skip
    if out:
        notes.append(
            "exhaust of the stories that are not conditioned: " + ", ".join(z["story"] for z in out)
        )
    return out


def zone_main(zone: dict[str, Any], rate: float = FRICTION_RATE) -> dict[str, Any] | None:
    """The main supply duct of a zone at its supply airflow."""
    if zone["airflow"] <= 0:
        return None
    return size_duct(zone["airflow"], "supply", "rect", rate)


# ─────────────────────────────────────── ducts ───────────────────────────────────────


def _story_flow(zone: dict[str, Any], system: str) -> float:
    """The airflow of ``system`` on a zone's story [m³/s]."""
    exhaust = zone["exhaust"]
    if system == "supply":
        return zone["airflow"]
    if system == "return":
        return max(zone["airflow"] - zone["outdoorAir"], 0.0)
    if system == "freshAir":
        return zone["outdoorAir"]
    if system == "exhaust":
        return exhaust["toilet"] + exhaust["general"]
    if system == "kitchenExhaust":
        return exhaust["kitchen"]
    return 0.0


def duct_flows(
    project: Project, zones: list[dict[str, Any]]
) -> tuple[dict[str, float], dict[str, str]]:
    """Airflow [m³/s] of each duct of the ``hvac`` section: its own ``flow``, else its story's
    flow of its system shared equally by the horizontal ducts of that system on the story; a
    riser carries the sum of the stories it passes (from its first to its last)."""
    by_story = {z["story"]: z for z in zones}
    ducts = project.hvac.get("ducts", [])
    count: dict[tuple[str, str], int] = {}
    for d in ducts:
        if not d.get("riser"):
            key = (d.get("story"), d.get("system", "supply"))
            count[key] = count.get(key, 0) + 1
    flows: dict[str, float] = {}
    sources: dict[str, str] = {}
    for d in ducts:
        system = d.get("system", "supply")
        if isinstance(d.get("flow"), int | float):
            flows[d["id"]] = float(d["flow"])
            sources[d["id"]] = "given"
            continue
        riser = d.get("riser")
        if riser:
            stories = project.building.between(riser.get("fromStory"), riser.get("toStory"))
            if not stories:
                order = project.order
                a, b = riser.get("fromStory"), riser.get("toStory")
                stories = (
                    order[order.index(a) : order.index(b) + 1] if a in order and b in order else []
                )
            total = sum(_story_flow(by_story[s], system) for s in stories if s in by_story)
            flows[d["id"]] = total
            sources[d["id"]] = f"sum of the {system} of {', '.join(stories) or 'no story'}"
            continue
        zone = by_story.get(d.get("story"))
        if zone is None:
            continue
        n = count.get((d.get("story"), system), 1)
        flows[d["id"]] = _story_flow(zone, system) / n
        sources[d["id"]] = f"{d.get('story')} {system}" + (f" / {n} ducts" if n > 1 else "")
    return flows, sources


def given_size(duct: dict[str, Any]) -> dict[str, Any] | None:
    if duct.get("shape") == "round" and duct.get("diameter"):
        return {"shape": "round", "diameter": float(duct["diameter"])}
    if duct.get("width") and duct.get("height"):
        return {"shape": "rect", "width": float(duct["width"]), "height": float(duct["height"])}
    return None


def duct_sizes(
    project: Project, zones: list[dict[str, Any]], rate: float = FRICTION_RATE
) -> tuple[list[dict[str, Any]], list[str]]:
    """Each duct of the ``hvac`` section sized (no size given) or checked (size given):
    ``[{"id", "system", "story", "riser", "flow", "flowSource", "size", "proposed",
    "velocity", "friction", "ok", "note"}]``."""
    flows, sources = duct_flows(project, zones)
    results = []
    notes = []
    for d in project.hvac.get("ducts", []):
        system = d.get("system", "supply")
        flow = flows.get(d["id"])
        given = given_size(d)
        if not flow:
            if given is not None:
                results.append({"id": d["id"], "system": system, "story": d.get("story"),
                                "riser": bool(d.get("riser")), "flow": None, "size": given,
                                "proposed": False, "velocity": None, "friction": None,
                                "ok": True, "note": "no airflow: size not checked"})  # fmt: skip
            else:
                notes.append(f"{d['id']}: no airflow and no size: not sized")
            continue
        if given is not None:
            check = check_duct(flow, given, system)
            size, proposed = given, False
            note = f"{check['velocity']:.2f} m/s against {check['limit']:g} m/s ({check['note']})"
            if check["minimum"] is not None:
                note += f", at least {check['minimum']:g} m/s"
        else:
            sized = size_duct(flow, system, d.get("shape") or "rect", rate)
            check = sized
            size = {k: sized[k] for k in ("shape", "width", "height", "diameter") if k in sized}
            proposed, note = True, sized["note"]
        results.append({
            "id": d["id"], "system": system, "story": d.get("story"),
            "riser": bool(d.get("riser")), "flow": flow, "flowSource": sources.get(d["id"], ""),
            "size": size, "proposed": proposed, "velocity": check["velocity"],
            "friction": check["friction"], "ok": check["ok"], "note": note,
        })  # fmt: skip
    return results, notes


# ─────────────────────────────────────── shafts ───────────────────────────────────────


def _riser_in(duct: dict[str, Any], polygon: Polygon, shaft_id: str) -> bool:
    if not duct.get("riser"):
        return False
    if duct.get("shaft") == shaft_id:
        return True
    path = duct.get("path") or []
    return bool(path) and polygon.covers(Point(path[0][0], path[0][1]))


def shaft_needs(
    project: Project, sizes: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The plan area each shaft of 07 MEP needs for the duct risers in it (and the plumbing
    risers of a given diameter) against its area: (shafts, checks)."""
    from saengine.plumbing.sleeves import outside_diameter
    from saengine.plumbing.tables import SHAFT_CLEARANCE as PIPE_CLEARANCE

    shafts, checks = [], []
    ducts = project.hvac.get("ducts", [])
    risers = project.mep.plumbing.risers if project.mep.plumbing else []
    for shaft in project.mep.shafts:
        polygon = Polygon(shaft.outline).buffer(0)
        inside = [d for d in ducts if _riser_in(d, polygon, shaft.id)]
        if not inside:
            continue
        need = 0.0
        items = []
        for d in inside:
            size = sizes.get(d["id"]) or given_size(d)
            if size is None:
                items.append({"id": d["id"], "need": None})
                continue
            w, h, _ = outside(d, size)
            a = (w + 2 * SHAFT_CLEARANCE) * (h + 2 * SHAFT_CLEARANCE)
            need += a
            items.append({"id": d["id"], "outside": [w, h], "need": a / 1e6})
        pipes = 0.0
        for r in risers:
            if r.diameter and (r.shaft == shaft.id or polygon.covers(Point(r.x, r.y))):
                pipes += (outside_diameter(r.diameter, r.material) + PIPE_CLEARANCE) ** 2
        need += pipes
        area = polygon.area
        kitchen = [d["id"] for d in inside if d.get("system") == "kitchenExhaust"]
        n_pipes = sum(
            1
            for r in risers
            if r.diameter and (r.shaft == shaft.id or polygon.covers(Point(r.x, r.y)))
        )
        if kitchen:
            count = len(inside) + n_pipes
            others = count - 1
            note = (
                "each kitchen exhaust duct enclosure contains only one exhaust duct, BNBC 2020 "
                "Part 8 Sec 2.11.5.1(f), p. 912"
            )
            if others:
                note += (
                    f": {', '.join(kitchen)} shares {shaft.id} with {others} other services; "
                    "give it its own fire-rated enclosure"
                )
            checks.append({
                "name": f"Shaft {shaft.id}: one kitchen exhaust duct only",
                "demand": float(count), "capacity": 1.0, "unit": "services",
                "utilisation": float(count), "ok": others == 0, "note": note,
            })  # fmt: skip
        ok = need <= area
        shafts.append({
            "id": shaft.id, "area": area / 1e6, "need": need / 1e6, "ducts": items,
            "pipes": pipes / 1e6, "ok": ok,
        })  # fmt: skip
        checks.append({
            "name": f"Shaft {shaft.id} area (HVAC risers)", "demand": need / 1e6,
            "capacity": area / 1e6, "unit": "m²",
            "utilisation": need / area if area else math.inf, "ok": ok,
            "note": f"{len(inside)} ducts, each (outside + 2 x {SHAFT_CLEARANCE:g} mm) "
            "both ways (SAEngine practice)" + (", and the plumbing risers" if pipes else ""),
        })  # fmt: skip
    return shafts, checks


# ─────────────────────────────────────── the report ───────────────────────────────────────


def _check(name: str, demand: float, capacity: float, unit: str, ok: bool, note: str):
    return {"name": name, "demand": demand, "capacity": capacity, "unit": unit,
            "utilisation": demand / capacity if capacity else math.inf, "ok": ok,
            "note": note}  # fmt: skip


#: The plant that makes the cooling: the plant's capacity is shared between them.
COOLING_SOURCES = ("chiller", "vrfOutdoor", "splitOutdoor")


def plant_requirements(
    plant: list[dict[str, Any]], capacity: dict[str, Any] | None, zones: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The plant rows with what each must give (``required``, ``unit``, ``utilisation``,
    ``ok``): a cooling source its share of the plant's capacity (:func:`saengine.hvac.plant.
    plant_capacity`, equal shares), an AHU the cooling load and a fresh air unit the outdoor air
    of the stories it serves. Rows with nothing to compare keep no utilisation."""
    by_story = {str(z.get("story")): z for z in zones}
    sources = [p for p in plant if p.get("kind") in COOLING_SOURCES]
    total = (capacity or {}).get("capacity")
    out = []
    for item in plant:
        row = dict(item)
        provided = row.get("capacity")
        serves = [by_story[s] for s in row.get("serves") or [] if s in by_story]
        need, unit, why = None, None, ""
        if row.get("kind") in COOLING_SOURCES and total:
            need, unit = total / len(sources), "kW"
            why = f"share of the plant's {total:.0f} kW ({len(sources)} units)"
        elif row.get("kind") == "ahu" and serves:
            need, unit = sum(z.get("total") or 0.0 for z in serves), "kW"
            why = "cooling load of the stories it serves"
        elif row.get("kind") == "freshAirUnit" and serves:
            need, unit = sum(z.get("outdoorAir") or 0.0 for z in serves), "m³/s"
            why = "outdoor air of the stories it serves (Table 8.2.3)"
        if need is not None:
            row["required"], row["unit"] = round(need, 3), unit
            if provided:
                row["utilisation"] = round(need / provided, 3)
                row["ok"] = need <= provided * (1 + 1e-6)
            note = row.get("note")
            row["note"] = f"{note}; {why}" if note else why
        out.append(row)
    return out


def hvac_air(
    project_root: str | Path,
    loads: dict[str, Any] | None = None,
    mep_text: str | None = None,
    *,
    dt: float = SUPPLY_DT,
    rate: float = FRICTION_RATE,
    with_plant: bool = True,
    with_openings: bool = True,
) -> dict[str, Any]:
    """The air side of the project's HVAC for the structure's coordination:
    ``{"zones": [{"story", "airflow", "outdoorAir", "ductMain", ...}], "ducts": [{"id",
    "size", "velocity", "ok", ...}], "shafts", "plant" (proposed 07 MEP plant entries),
    "openings" (proposed 07 MEP openings), "conflicts" (ducts that cannot pass a beam, with
    the options), "checks": [{name, demand, capacity, unit, utilisation, ok, note}], "notes",
    "problems"}``. ``loads``: the HVAC load calculation's result (H1); None runs it."""
    project = load_project(project_root, mep_text)
    notes: list[str] = []
    if loads is None:
        loads = _hvac_loads(project_root, mep_text)
        if loads is None:
            notes.append("the HVAC load calculation is not available: no zone airflows")
    zones, more = zone_air(project, loads, dt)
    notes += more
    for zone in zones:
        main = zone_main(zone, rate)
        zone["ductMain"] = (
            {k: main[k] for k in ("shape", "width", "height", "velocity", "friction", "governs")}
            if main
            else None
        )
    ducts, more = duct_sizes(project, zones, rate)
    notes += more
    sizes = {d["id"]: {**d["size"], "flow": d["flow"]} for d in ducts}
    shafts, checks = shaft_needs(project, sizes)
    for d in ducts:
        if d["velocity"] is None:
            continue
        _, vmax, source = VELOCITY.get(d["system"], VELOCITY["supply"])
        checks.append(_check(f"Duct {d['id']} velocity", d["velocity"], vmax, "m/s", d["ok"],
                             d["note"] or source))  # fmt: skip
    result: dict[str, Any] = {
        "zones": zones, "ducts": ducts, "shafts": shafts, "plant": [], "pipes": [],
        "openings": [], "conflicts": [], "checks": checks, "notes": notes,
        "problems": list(project.problems),
        "method": {"supplyDeltaT": dt, "frictionRate": rate, "aspectMax": ASPECT_MAX,
                   "roughness": ROUGHNESS, "velocity": {k: v[1] for k, v in VELOCITY.items()}},
    }  # fmt: skip
    if with_plant:
        from saengine.hvac.plant import coincident_peak, propose_plant

        plant = propose_plant(project, zones, coincident=coincident_peak(loads))
        result["plant"] = plant_requirements(plant["plant"], plant["capacity"], zones)
        result["pipes"] = plant["pipes"]
        result["equipment"] = plant["equipment"]
        result["checks"] += plant["checks"]
        result["notes"] += plant["notes"]
    if with_openings:
        from saengine.hvac.openings import duct_openings

        found = duct_openings(project, sizes)
        result["openings"] = found["openings"]
        result["conflicts"] = found["conflicts"]
        result["stale"] = found.get("stale", [])
        result["checks"] += found["checks"]
        result["notes"] += found["notes"]
    return result

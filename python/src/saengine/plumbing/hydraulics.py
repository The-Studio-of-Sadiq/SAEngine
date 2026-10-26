"""Water-supply hydraulics of a building (Part 7, plumbing coordination): heads at the floors, the
pressure zones of a tall building, the transfer pump and the city main.

The network is built from the ``plumbing`` section of ``07 MEP/mep.json`` and solved with WNTR
(the EPA/Sandia Water Network Tool for Resilience, revised BSD) running EPANET 2.2 (MIT), the
standard solver of pipe networks:

* each overhead tank is a fixed-head source (a WNTR reservoir) at its minimum water level: the
  story it stands on + its base slab + the 50 mm the outlet stands above the tank bottom (BNBC
  2020 Part 8 Sec 5.9.2.2): the steady state at the end of a draw-down, the worst case;
* a header from the tank outlet to the top of each cold-water down-feed riser (horizontal at
  the outlet level, its length the plan distance |dx| + |dy|), the riser a chain of pipes
  between the take-offs at the floors it serves, and from each take-off a floor branch to a
  demand node at the critical fixture (the shower rose where the floor has showers, else the
  1 m of a tap);
* the demands are the probable simultaneous demands of BNBC Table 8.5.5 (flush tanks; flush
  valves when the supply says so) of the fixture units the riser carries, counted from its far
  end: each riser segment carries the Table 8.5.5 flow of all the fixture units below it (down
  feed), each floor branch the flow of its own floor;
* Hazen-Williams friction (BNBC Sec 5.10.3 allows it for building pipes); fittings as
  equivalent pipe lengths from BNBC Tables 8.O.2(a)-(c).

The results are the residual heads at the take-offs and fixtures against the minimum flow
pressure of BNBC Table 8.5.6 (55 kPa, 100 kPa for flush valves) during the peak (Sec 5.10.4.3),
the static head with the tank full against the 35 m (345 kPa) of Sec 5.10.4.2 (Sec 5.11.1: 350
kPa) with the pressure zones a tall building needs (Sec 5.11.1: intermediate tanks or pressure
reducing valves), the velocities against the probable maximum velocities of Sec 5.10.1(c)(ii),
the transfer pump from the underground reservoir to the overhead tank (its flow the delivery
pump capacity of Sec 5.9.1.2(c)(ii) as the plumbing sizing finds it; its head Sec 5.10.5, eq.
8.5.2 and 8.5.3) and whether the city main reaches the reservoir, the lower floors and the roof tank
(Secs 5.8.1-5.8.3).

Units: the contract (mep.json) in mm; inside and in the results m, m³/s (reported L/s), m/s,
kW. Heads in the results are pressure heads (m of water above the point) unless named a level.
"""

from __future__ import annotations

import json
import math
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from saengine.plumbing import tables as T
from saengine.plumbing.demand import hunter_flow, supply_units
from saengine.plumbing.supply import size_pipe, velocity_limit

G = 9.80665  # m/s²
RHO = 1000.0  # kg/m³, water
KPA_PER_M = 9.807  # kPa per metre of water, as BNBC eq. 8.O.1

BIM_FILE = "06 BIM/bim.json"
MEP_FILE = "07 MEP/mep.json"
SETTINGS_FILE = "02 Project Settings/project-settings.json"

# ─────────────────────────────────── BNBC 2020 Part 8 data ───────────────────────────────────
# The tables of the plumbing sizing (saengine.plumbing.tables: Table 8.5.5, the supply fixture
# units of Tables 8.O.1 and 8.5.4, the velocity limits of Sec 5.10.1(c)(ii), Table 8.5.6's flow
# pressures, Sec 5.10.4.2's 35 m, the Hazen-Williams C) are shared, so that the hydraulics and
# the sizing agree; this module adds what only the network needs.

#: Minimum flow pressure at the fixtures, BNBC Table 8.5.6 (p. 1047) [kPa].
REQUIRED_KPA = T.FLOW_PRESSURE_TANK
REQUIRED_KPA_FLUSH_VALVE = T.FLOW_PRESSURE_VALVE
#: Maximum water head on any fitting, BNBC Sec 5.10.4.2 (p. 1047): 35 m (345 kPa); Sec 5.11.1
#: (p. 1049) gives 350 kPa for tall buildings.
MAX_HEAD = T.MAX_STATIC_HEAD
#: Maximum permissible head loss, BNBC Sec 5.10.1(c)(ii) (p. 1044): 1.5-1.6 m per 100 m.
MAX_GRADIENT = T.MAX_HEAD_LOSS / 100.0
#: Hazen-Williams C by pipe material (BNBC gives only the C = 100 nomograph, Figure 8.O.4).
HAZEN_C = T.HAZEN_C

#: Required flow rate of a single fixture [L/min], BNBC Table 8.5.6 (p. 1047): the least flow a
#: floor branch carries (below the 20 units where Table 8.5.5 starts it can give less).
#: Pedestal urinal 56.8 L/min with a flush tank or a flushometer valve alike.
FIXTURE_FLOW = {"wc": 11.4, "urinal": 56.8, "shower": 11.4, "bathtub": 15.1, "kitchenSink": 9.5}
FIXTURE_FLOW_FLUSH_VALVE_WC = 132.0

#: The outlet of a storage tank at least 50 mm above its bottom, BNBC Sec 5.9.2.2 (p. 1043).
OUTLET_ABOVE_BOTTOM = 0.050

#: Equivalent lengths of fittings [m], BNBC Tables 8.O.2(a)-(c) (pp. 1197-1199), by nominal
#: size [mm].
FITTING_SIZES = (13, 19, 25, 32, 38, 50, 63, 75, 88, 100, 125, 150, 200)
FITTINGS = {
    # Table 8.O.2(a) smooth bend elbow 90° standard
    "elbow": (0.49, 0.61, 0.79, 1.01, 1.22, 1.53, 1.83, 2.29, 2.75, 3.05, 3.97, 4.88, 6.10),
    # Table 8.O.2(b) smooth bend tee, flow through the branch
    "teeBranch": (0.92, 1.22, 1.53, 2.14, 2.44, 3.05, 3.66, 4.58, 5.49, 6.41, 7.63, 9.15, 12.20),
    # Table 8.O.2(b) smooth bend tee, straight-through flow, no reduction
    "teeRun": (0.31, 0.43, 0.52, 0.70, 0.79, 1.01, 1.25, 1.53, 1.80, 2.04, 2.50, 3.05, 3.97),
    # Table 8.O.2(c) gate valve
    "gate": (0.21, 0.27, 0.31, 0.46, 0.55, 0.70, 0.85, 0.98, 1.22, 1.37, 1.83, 2.14, 2.75),
    # Table 8.O.2(c) swing check valve
    "check": (1.83, 2.44, 3.05, 4.27, 4.88, 6.10, 7.63, 9.15, 10.68, 12.20, 15.25, 18.30, 24.40),
}
#: The fittings SAEngine allows on each kind of pipe (its own allowance, not BNBC's).
HEADER_FITTINGS = {"elbow": 2, "gate": 1}  # tank outlet valve and two bends
RISER_FITTINGS = {"teeRun": 1}  # the take-off tee of each floor
BRANCH_FITTINGS = {"teeBranch": 1, "gate": 1, "elbow": 4}  # floor control valve (Sec 5.8)
PUMP_FITTINGS = {"check": 1, "gate": 2, "elbow": 4}


#: The standard rated outputs of motors [kW] (IEC 60072-1), from the smallest pump motor
#: commonly sold (0.37 kW, 0.5 hp): the pump is chosen at the next one up from the shaft power.
MOTOR_RATINGS = (0.37, 0.55, 0.75, 1.1, 1.5, 2.2, 3.0, 4.0, 5.5, 7.5, 11.0, 15.0, 18.5, 22.0,
                 30.0, 37.0, 45.0, 55.0, 75.0)  # fmt: skip


def motor_rating(shaft_kw: float) -> float:
    """The pump's motor [kW]: the smallest standard rated output (IEC 60072-1) at or above the
    shaft power, at least 0.37 kW (a pump of a few watts is not made); above the list, the
    shaft power itself."""
    return next((r for r in MOTOR_RATINGS if r >= shaft_kw - 1e-9), round(shaft_kw, 2))


def probable_demand(units: float, flush_valves: bool = False, least: float = 0.0) -> float:
    """Probable simultaneous demand [L/min] of ``units`` supply fixture units, BNBC Table 8.5.5
    (:func:`saengine.plumbing.demand.hunter_flow`), and at least ``least`` (the largest single
    fixture's flow of Table 8.5.6) when there are any units."""
    if units <= 0:
        return 0.0
    return max(hunter_flow(units, flush_valves), least)


def hazen_williams_loss(flow: float, diameter: float, length: float, c: float) -> float:
    """Friction head loss [m] of ``flow`` [m³/s] in a pipe of ``diameter`` and ``length`` [m]:
    h = 10.667 L Q^1.852 / (C^1.852 D^4.871) (SI Hazen-Williams, the form EPANET uses)."""
    if flow == 0:
        return 0.0
    q = abs(flow)
    return 10.667 * length * q**1.852 / (c**1.852 * diameter**4.871) * math.copysign(1, flow)


def fitting_length(diameter_mm: float, fittings: dict[str, int]) -> float:
    """Equivalent pipe length [m] of ``fittings`` (name -> count) at a size, BNBC Tables
    8.O.2(a)-(c), linear between the sizes of the tables."""
    total = 0.0
    for name, count in fittings.items():
        total += count * _interp(diameter_mm, FITTING_SIZES, FITTINGS[name])
    return total


def _interp(x: float, xs: tuple[float, ...], ys: tuple[float, ...]) -> float:
    if x <= xs[0]:
        return ys[0]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            t = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] + t * (ys[i] - ys[i - 1])
    return ys[-1]


def size_for_flow(flow: float, material: str | None = None, smallest: float = 0.0) -> float | None:
    """The size the plumbing sizing gives [mm] for ``flow`` [m³/s]: the smallest of BNBC's
    sizes within the velocity limit and 1.6 m/100 m (:func:`saengine.plumbing.supply.size_pipe`);
    None above 200 mm."""
    found = size_pipe(flow * 60000, material, smallest)["diameter"]
    return None if found is None else float(found)


def _velocity(flow: float, diameter: float) -> float:
    return abs(flow) / (math.pi * diameter**2 / 4) if diameter > 0 else 0.0


# ─────────────────────────────────────── options ───────────────────────────────────────


@dataclass
class HydraulicOptions:
    """What the analysis assumes where the contract is silent (SAEngine defaults)."""

    #: Height of a tap above its floor [m]; the critical fixture of a floor with showers is the
    #: shower rose at ``showerHeight``.
    fixtureHeight: float = 1.0
    showerHeight: float = 2.0
    #: Take-off of the floor branch above the floor level [m].
    takeoffHeight: float = 0.0
    #: Horizontal length of a floor branch from the riser to the critical fixture [m].
    branchLength: float = 10.0
    #: Flush valves (flushometers) instead of flush tanks: Table 8.5.5's right-hand column,
    #: Table 8.O.1's units for water closets and urinals, 100 kPa at the fixtures.
    flushValves: bool = False
    #: Defaults of a tank whose dimensions the contract leaves out [mm].
    tankBase: float = 200.0
    tankRoof: float = 150.0
    tankFreeboard: float = 300.0
    tankWaterDepth: float = 1500.0
    #: Pump: its flow [L/min] when given (else the plumbing sizing's delivery pump flow, BNBC
    #: Sec 5.9.1.2(c)(ii): the peak hourly demand), pump efficiency (BNBC eq. 8.5.2 leaves it
    #: to the pump), the residual head the float valve at the tank inlet needs [m].
    pumpFlow: float | None = None
    pumpEfficiency: float = 0.60
    inletResidual: float = 1.0
    #: Hazen-Williams C of a riser without a material.
    defaultMaterial: str = "uPVC"

    @classmethod
    def of(cls, value: HydraulicOptions | dict[str, Any] | None) -> HydraulicOptions:
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in dict(value).items() if k in names})


# ───────────────────────────────────── the network ─────────────────────────────────────


@dataclass
class _Story:
    id: str
    name: str
    elevation: float  # m


@dataclass
class _Floor:
    """A floor a riser serves."""

    story: _Story
    units: float  # supply fixture units of the floor on this riser
    least: float  # L/min, the largest single fixture's flow
    minimum: float  # mm, the largest minimum supply pipe of its fixtures (Table 8.5.6)
    fixture_height: float  # m above the floor
    required: float  # m, the minimum pressure head at the fixture
    takeoff: str = ""
    fixture: str = ""
    segment: str = ""  # the riser pipe that feeds this take-off
    branch: str = ""
    branch_diameter: float = 0.0  # mm
    branch_flow: float = 0.0  # m³/s
    segment_flow: float = 0.0  # m³/s


@dataclass
class _Riser:
    id: str
    x: float  # m
    y: float
    material: str
    c: float
    diameter: float  # mm
    sized: bool
    source: str  # tank id or "mains"
    source_level: float  # m, minimum water level (head of the source)
    full_level: float  # m, the top water level (static checks)
    upfeed: bool
    floors: list[_Floor] = field(default_factory=list)  # from the source end
    header: str = ""
    header_length: float = 0.0
    start: float = 0.0  # m, level of the header (tank bottom; the connection for the main)
    flow: float = 0.0  # m³/s at the source


def _dump(value: Any) -> Any:
    """A pydantic model as JSON-like data (by alias), anything else as it is."""
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    return value


def _plumbing_of(mep: Any) -> dict[str, Any]:
    """The ``plumbing`` section of an MEP model, its JSON, or the section itself."""
    data = _dump(mep)
    if data is None:
        return {}
    if isinstance(data, str):
        data = json.loads(data) if data.strip() else {}
    if not isinstance(data, dict):
        return {}
    if "plumbing" in data:
        return _dump(data["plumbing"]) or {}
    if any(k in data for k in ("risers", "tanks", "stories", "supply")):
        return data
    return {}


def _stories(building: Any) -> list[_Story]:
    data = _dump(building) or {}
    stories = [
        _Story(str(s["id"]), str(s.get("name") or s["id"]), float(s["elevation"]) / 1000.0)
        for s in (data.get("stories") or [])
    ]
    return sorted(stories, key=lambda s: s.elevation)


def floor_units(
    entry: dict[str, Any], flush_valves: bool = False, column: str = "total"
) -> tuple[float, float, bool, float]:
    """What a floor (a ``plumbing.stories[]`` entry) draws: its supply fixture units in
    ``column`` (cold, hot or total) by :func:`saengine.plumbing.demand.supply_units` (Table
    8.O.1, Table 8.5.4 for the fixtures it does not list), the largest single fixture's flow
    [L/min] (Table 8.5.6), whether it has showers and the largest minimum supply pipe [mm]
    (Table 8.5.6)."""
    data = entry.get("fixtures") or {}
    names = ("wc", "urinal", "basin", "shower", "bathtub", "kitchenSink", "floorDrain",
             "washingMachine", "bidet")  # fmt: skip
    counts = {name: int(data.get(name) or 0) for name in names}
    other = [
        SimpleNamespace(
            name=str(o.get("name") or "other"),
            count=int(o.get("count") or 0),
            supplyUnits=float(o.get("supplyUnits") or 0),
            drainageUnits=float(o.get("drainageUnits") or 0),
        )
        for o in data.get("other") or []
    ]
    units, minimum, _ = supply_units(SimpleNamespace(**counts, other=other), column, flush_valves)
    least = 0.0
    for name, flow in FIXTURE_FLOW.items():
        if counts.get(name):
            if flush_valves and name == "wc":
                flow = FIXTURE_FLOW_FLUSH_VALVE_WC
            least = max(least, flow)
    return float(units), least, counts["shower"] > 0, float(minimum)


@dataclass
class _Tank:
    id: str
    kind: str
    x: float
    y: float
    level: float  # m, minimum water level (outlet)
    full: float  # m, top water level
    inlet: float  # m, the inlet (underside of the roof slab)
    bottom: float  # m, inside bottom
    volume: float  # m³
    story_elevation: float | None


def _tank(
    t: dict[str, Any],
    stories: dict[str, _Story],
    ground: float,
    o: HydraulicOptions,
    sizing: dict[str, Any],
    notes: list[str],
) -> _Tank | None:
    kind = str(t.get("kind") or "")
    tid = str(t.get("id") or kind)
    sized = (sizing.get("tanks") or {}).get(tid) or {}
    depth = float(t.get("waterDepth") or sized.get("waterDepth") or 0) / 1000
    if depth <= 0:
        depth = o.tankWaterDepth / 1000
        notes.append(f"{tid}: no water depth given: {o.tankWaterDepth:g} mm assumed.")

    def given(name: str, default: float) -> float:
        # an explicit 0 (a prefab tank set on the slab, no freeboard) is kept
        value = t.get(name)
        return float(default if value is None else value) / 1000

    base = given("base", o.tankBase)
    roof = given("roof", o.tankRoof)
    freeboard = given("freeboard", o.tankFreeboard)
    length = float(t.get("length") or sized.get("length") or 0) / 1000
    width = float(t.get("width") or sized.get("width") or 0) / 1000
    # the partitions (compartments - 1 walls; not given: 2 compartments) take their share
    parts = (int(t.get("compartments") or 2) - 1) * float(t.get("walls") or 200.0) / 1000
    volume = float(sized.get("volume") or 0) or max(length - parts, 0.0) * width * depth
    x, y = float(t.get("x") or 0) / 1000, float(t.get("y") or 0) / 1000
    if kind == "overhead":
        story = stories.get(str(t.get("story")))
        if story is None:
            return None
        bottom = story.elevation + base
        return _Tank(
            tid,
            kind,
            x,
            y,
            bottom + OUTLET_ABOVE_BOTTOM,
            bottom + depth,
            bottom + depth + freeboard,
            bottom,
            volume,
            story.elevation,
        )
    top = ground + float(t.get("topLevel") or 0) / 1000
    inside_top = top - roof
    bottom = inside_top - freeboard - depth
    return _Tank(tid, kind, x, y, bottom, bottom + depth, inside_top, bottom, volume, None)


def _material_c(material: str | None, o: HydraulicOptions) -> tuple[str, float]:
    name = material or o.defaultMaterial
    return name, HAZEN_C.get(name, HAZEN_C["uPVC"])


# ────────────────────────────────────── the analysis ──────────────────────────────────────

_EPANET = threading.Lock()


def _solve(wn: Any) -> Any:
    """Run EPANET 2.2 through WNTR on ``wn`` in a scratch folder (its .inp/.rpt/.bin files)."""
    import wntr

    with _EPANET, tempfile.TemporaryDirectory(prefix="saengine-wntr-") as folder:
        sim = wntr.sim.EpanetSimulator(wn)
        return sim.run_sim(file_prefix=str(Path(folder) / "net"))


def _new_network() -> Any:
    import wntr

    wn = wntr.network.WaterNetworkModel()
    wn.options.hydraulic.headloss = "H-W"
    wn.options.time.duration = 0
    return wn


def _check(
    name: str, demand: float, capacity: float, unit: str, note: str = "", ok: bool | None = None
) -> dict[str, Any]:
    utilisation = demand / capacity if capacity > 0 else None
    passed = ok if ok is not None else (utilisation is not None and utilisation <= 1 + 1e-9)
    return {
        "name": name,
        "demand": round(demand, 4),
        "capacity": round(capacity, 4),
        "unit": unit,
        "utilisation": None if utilisation is None else round(utilisation, 4),
        "ok": bool(passed),
        "note": note,
    }


def _load(project_root: str | Path) -> tuple[Any, Any, float]:
    root = Path(project_root)

    def read(relative: str) -> str | None:
        try:
            return (root / relative).read_text(encoding="utf-8")
        except OSError:
            return None

    bim = read(BIM_FILE)
    if bim is None:
        raise ValueError(f"{BIM_FILE} could not be read")
    mep = read(MEP_FILE)
    settings = read(SETTINGS_FILE)
    ground = 0.0
    if settings:
        try:
            ground = float(json.loads(settings).get("foundation", {}).get("groundLevel", 0.0))
        except (ValueError, AttributeError):
            ground = 0.0
    return json.loads(bim), json.loads(mep) if mep and mep.strip() else {}, ground


def water_hydraulics(
    project_root: str | Path | None = None,
    *,
    building: Any = None,
    mep: Any = None,
    sizing: dict[str, Any] | None = None,
    ground_level: float | None = None,
    options: HydraulicOptions | dict[str, Any] | None = None,
    units_of: Callable[..., tuple[float, float, bool, float]] | None = None,
) -> dict[str, Any]:
    """The water-supply hydraulics of a project folder or of ``building`` (06 BIM, model or
    JSON data) and ``mep`` (07 MEP model, its data or its ``plumbing`` section).

    ``sizing`` (optional, what the plumbing sizing proposed): ``{"risers": {id: {"diameter":
    mm}}, "tanks": {id: {"volume": m³, "waterDepth": mm, "length": mm, "width": mm}}}``.
    ``ground_level`` [mm] (Project Settings' foundation.groundLevel; read from the folder).
    ``units_of(story entry, flush_valves, column) -> (units, least flow L/min, has showers,
    minimum pipe mm)`` replaces :func:`floor_units`.

    Returns ``{floors, risers, pump, zones, mains, checks, notes, problems}``."""
    ground_mm = 0.0
    if project_root is not None:
        building, mep_data, ground_mm = _load(project_root)
        if mep is None:
            mep = mep_data
    if ground_level is not None:
        ground_mm = float(ground_level)
    o = HydraulicOptions.of(options)
    sizing = sizing or {}
    units_of = units_of or floor_units
    plumbing = _plumbing_of(mep)
    ground = ground_mm / 1000
    notes: list[str] = []
    problems: list[str] = []
    checks: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "floors": [],
        "risers": [],
        "pump": None,
        "zones": [],
        "mains": None,
        "checks": checks,
        "notes": notes,
        "problems": problems,
    }
    stories_sorted = _stories(building)
    stories = {s.id: s for s in stories_sorted}
    if not plumbing:
        problems.append("07 MEP has no plumbing section: nothing to analyse.")
        return result
    if not stories_sorted:
        problems.append("06 BIM has no stories.")
        return result

    supply = plumbing.get("supply") or {}
    flush = bool(supply.get("flushValves", o.flushValves))
    required_default = (REQUIRED_KPA_FLUSH_VALVE if flush else REQUIRED_KPA) / KPA_PER_M
    required = float(supply.get("minResidualHead") or required_default)

    tanks: list[_Tank] = []
    for t in plumbing.get("tanks") or []:
        t = _dump(t)
        if t.get("kind") not in ("overhead", "underground"):
            continue
        tank = _tank(t, stories, ground, o, sizing, notes)
        if tank is None:
            problems.append(f"{t.get('id')}: an overhead tank needs the story it stands on.")
        else:
            tanks.append(tank)
    overhead = sorted((t for t in tanks if t.kind == "overhead"), key=lambda t: t.level)
    underground = [t for t in tanks if t.kind == "underground"]

    entries = {str(e.get("story")): _dump(e) for e in plumbing.get("stories") or []}
    for sid in entries:
        if sid not in stories:
            problems.append(f"plumbing story '{sid}' is not a story of 06 BIM.")
    raw_risers = [_dump(r) for r in plumbing.get("risers") or []]
    # as the riser sizing: cold units where there are hot-water risers, else the total (the
    # cold riser then feeds the water heaters too)
    column = "cold" if any(r.get("system") == "hotWater" for r in raw_risers) else "total"
    floor_data = {sid: units_of(e, flush, column) for sid, e in entries.items() if sid in stories}

    cold = [r for r in raw_risers if r.get("system") == "coldWater"]
    if not cold and overhead and floor_data:
        top = overhead[-1]
        below = [s.id for s in stories_sorted if s.elevation < top.story_elevation - 1e-9]
        if below:
            cold = [
                {
                    "id": "R-auto",
                    "system": "coldWater",
                    "x": top.x * 1000,
                    "y": top.y * 1000,
                    "fromStory": below[0],
                    "toStory": below[-1],
                }
            ]
            notes.append(
                "No cold-water riser in 07 MEP: one down-feed riser assumed at the overhead "
                f"tank {top.id}, serving every floor below it."
            )

    # how many risers serve each story: its units are shared equally among them
    risers: list[_Riser] = []
    served: dict[str, list[str]] = {}
    plans: list[tuple[dict[str, Any], list[_Story], _Tank | None]] = []
    for r in cold:
        rid = str(r.get("id"))
        lo, hi = stories.get(str(r.get("fromStory"))), stories.get(str(r.get("toStory")))
        if lo is None or hi is None:
            problems.append(f"{rid}: its from/to story is not a story of 06 BIM.")
            continue
        if hi.elevation < lo.elevation:
            lo, hi = hi, lo
        passes = [
            s for s in stories_sorted if lo.elevation - 1e-9 <= s.elevation <= hi.elevation + 1e-9
        ]
        if r.get("serves"):
            wanted = {str(s) for s in r["serves"]}
            passes = [s for s in passes if s.id in wanted]
        passes = [s for s in passes if floor_data.get(s.id, (0.0,))[0] > 0]
        tank = next((t for t in overhead if t.story_elevation >= hi.elevation - 1e-9), None)
        if tank is None and overhead:
            tank = overhead[-1]
        plans.append((r, passes, tank))
        for s in passes:
            served.setdefault(s.id, []).append(rid)
    for sid in floor_data:
        if floor_data[sid][0] > 0 and sid not in served:
            notes.append(f"{stories[sid].name}: no cold-water riser serves its fixtures.")

    for r, passes, tank in plans:
        rid = str(r.get("id"))
        material, c = _material_c(r.get("material"), o)
        x, y = float(r.get("x") or 0) / 1000, float(r.get("y") or 0) / 1000
        if tank is not None:
            source, level, full, upfeed = tank.id, tank.level, tank.full, False
        elif supply.get("source") == "mains" and supply.get("mainsHead") is not None:
            level = full = ground + float(supply["mainsHead"])
            source, upfeed = "mains", True
            notes.append(f"{rid}: no overhead tank: fed up from the city main (BNBC Sec 5.8.1).")
        else:
            problems.append(f"{rid}: no overhead tank feeds it and no mains head is given.")
            continue
        floors = []
        for s in passes:
            units, least, shower, minimum = floor_data[s.id]
            share = len(served[s.id])
            floors.append(
                _Floor(
                    story=s,
                    units=units / share,
                    least=least,
                    minimum=minimum,
                    fixture_height=o.showerHeight if shower else o.fixtureHeight,
                    required=required,
                )
            )
        # from the source end: down-feed from the top, up-feed from the bottom
        floors.sort(key=lambda f: f.story.elevation, reverse=not upfeed)
        diameter = float(
            r.get("diameter") or (sizing.get("risers") or {}).get(rid, {}).get("diameter") or 0
        )
        riser = _Riser(
            rid, x, y, material, c, diameter, diameter <= 0, source, level, full, upfeed, floors
        )
        if tank is not None:
            riser.header_length = abs(tank.x - x) + abs(tank.y - y)
            riser.start = tank.bottom
        else:
            riser.start = ground
        risers.append(riser)

    floors_out, zones = _network(risers, o, flush, checks, notes, problems)
    result["floors"] = floors_out
    result["risers"] = [
        {
            "id": r.id,
            "source": r.source,
            "diameter": r.diameter,
            "sized": r.sized,
            "material": r.material,
            "hazenC": r.c,
            "flow": round(r.flow * 1000, 4),
            "units": round(sum(f.units for f in r.floors), 3),
            "sourceLevel": round(r.source_level, 4),
            "fullLevel": round(r.full_level, 4),
            "floors": [f.story.id for f in r.floors],
        }
        for r in risers
    ]
    for z in zones:
        # where a proposed intermediate tank can stand: the highest story at or below its bottom
        if z["solved"]:
            below = [s for s in stories_sorted if s.elevation <= z["tankBottom"] + 1e-9]
            if below:
                z["standsOn"] = below[-1].id
                z["base"] = round((z["tankBottom"] - below[-1].elevation) * 1000, 1)  # mm
    result["zones"] = zones
    if overhead:
        result["pump"] = _pump(
            overhead, underground, raw_risers, supply, o, checks, notes, problems,
            plumbing, building,
        )  # fmt: skip
    if supply.get("source") == "mains":
        result["mains"] = _mains(
            supply, ground, stories_sorted, underground, overhead, o, required, checks, problems,
            notes,
        )  # fmt: skip
    elif supply.get("source") == "deepTubewell":
        notes.append(
            "Source: deep tube well (BNBC Sec 5.8.4): its pump into the reservoir is not analysed."
        )
    notes.extend(_method_notes(o, flush, required))
    return result


def _method_notes(o: HydraulicOptions, flush: bool, required: float) -> list[str]:
    return [
        (
            "Network solved with WNTR (EPANET 2.2), Hazen-Williams friction (BNBC 2020 Part 8 Sec "
            "5.10.3); C by material: uPVC/PPR/HDPE 150, GI 120, CI 100 (BNBC gives only the C = "
            "100 nomograph, Figure 8.O.4)."
        ),
        (
            "Overhead tank as a fixed head at its minimum water level (outlet 50 mm above the "
            "bottom, Sec 5.9.2.2); static heads with the tank full."
        ),
        (
            "Demands: probable simultaneous demand of Table 8.5.5 "
            f"({'flush valves' if flush else 'flush tanks'}) of the fixture units each riser "
            "segment carries, units from Tables 8.5.4 and 8.O.1."
        ),
        (
            "Fittings as equivalent lengths of Tables 8.O.2(a)-(c): floor branch "
            f"{o.branchLength:g} m + rise with a branch tee, a gate valve and 4 elbows; a run "
            "tee per floor on the riser; 2 elbows and a gate valve on the header (SAEngine "
            "allowances)."
        ),
        (
            f"Minimum head at the fixtures {required:.2f} m ({required * KPA_PER_M:.0f} kPa, Table "
            "8.5.6); maximum 35 m (345 kPa, Sec 5.10.4.2) on any fitting."
        ),
        (
            "Velocities against the probable maximum velocities of Sec 5.10.1(c)(ii) (13 mm 0.30, "
            "50 mm 0.60, 75 mm 0.75, 100 mm 0.90, 150 mm 1.15, 200 mm 1.30 m/s, linear between, "
            "as the plumbing sizing reads them); pipes SAEngine sizes also within 1.6 m/100 m."
        ),
    ]


def _network(
    risers: list[_Riser],
    o: HydraulicOptions,
    flush: bool,
    checks: list[dict[str, Any]],
    notes: list[str],
    problems: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not risers:
        return [], []
    wn = _new_network()
    for r in risers:
        _add_riser(wn, r, o, flush, problems)
    results = _solve(wn)
    return _floor_results(risers, results, o, checks, notes, flush, problems)


def _add_riser(
    wn: Any, r: _Riser, o: HydraulicOptions, flush: bool, problems: list[str] | None
) -> None:
    """Add a riser to ``wn``: its source, header, segments, take-offs, branches and fixtures
    (sizing the riser when it has no diameter, the branches always)."""
    # flows: each segment carries the Table 8.5.5 flow of the units from the far end
    far = list(reversed(r.floors))
    cumulative = least = 0.0
    for f in far:
        cumulative += f.units
        least = max(least, f.least)
        f.segment_flow = probable_demand(cumulative, flush, least) / 60000
        f.branch_flow = probable_demand(f.units, flush, f.least) / 60000
    r.flow = r.floors[0].segment_flow if r.floors else 0.0
    if r.sized:
        smallest = max((f.minimum for f in r.floors), default=0.0)
        found = size_for_flow(r.flow, r.material, smallest)
        if found is None and problems is not None:
            problems.append(f"{r.id}: more than a 200 mm riser: split it into more risers.")
        r.diameter = found or 200.0
    d = r.diameter / 1000
    src = f"{r.id}:src"
    wn.add_reservoir(src, base_head=r.source_level)
    top = f"{r.id}:top"
    wn.add_junction(top, base_demand=0.0, elevation=r.start)
    r.header = f"{r.id}:header"
    length = max(r.header_length, 0.1) + fitting_length(r.diameter, HEADER_FITTINGS)
    wn.add_pipe(r.header, src, top, length=length, diameter=d, roughness=r.c)
    previous, previous_z = top, r.start
    for i, f in enumerate(r.floors):
        z = f.story.elevation + o.takeoffHeight
        f.takeoff, f.fixture = f"{r.id}:{f.story.id}:t", f"{r.id}:{f.story.id}:f"
        f.segment, f.branch = f"{r.id}:{f.story.id}:s", f"{r.id}:{f.story.id}:b"
        # the take-off draws the riser's flow increment; the branch carries the floor's
        # own probable flow, the difference is the diversity of the riser (a negative
        # demand at the take-off when the floor's own flow is the larger)
        nxt = r.floors[i + 1].segment_flow if i + 1 < len(r.floors) else 0.0
        increment = f.segment_flow - nxt
        wn.add_junction(f.takeoff, base_demand=increment - f.branch_flow, elevation=z)
        seg_length = abs(previous_z - z) + fitting_length(r.diameter, RISER_FITTINGS)
        wn.add_pipe(
            f.segment,
            previous,
            f.takeoff,
            length=max(seg_length, 0.1),
            diameter=d,
            roughness=r.c,
        )
        f.branch_diameter = size_for_flow(f.branch_flow, r.material, f.minimum) or 200.0
        zf = f.story.elevation + f.fixture_height
        wn.add_junction(f.fixture, base_demand=f.branch_flow, elevation=zf)
        b_length = o.branchLength + abs(zf - z) + fitting_length(f.branch_diameter, BRANCH_FITTINGS)
        wn.add_pipe(
            f.branch,
            f.takeoff,
            f.fixture,
            length=b_length,
            diameter=f.branch_diameter / 1000,
            roughness=r.c,
        )
        previous, previous_z = f.takeoff, z


def _floor_results(
    risers: list[_Riser],
    results: Any,
    o: HydraulicOptions,
    checks: list[dict[str, Any]],
    notes: list[str],
    flush: bool,
    problems: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pressure = results.node["pressure"].iloc[0]
    velocity = results.link["velocity"].iloc[0]
    flowrate = results.link["flowrate"].iloc[0]

    out = []
    for r in risers:
        v_header = float(velocity[r.header])
        limit = velocity_limit(r.diameter)
        checks.append(
            _check(
                f"Velocity in the header of {r.id} (Ø{r.diameter:g})",
                v_header,
                limit,
                "m/s",
                "BNBC Sec 5.10.1(c)(ii)",
            )
        )
        for f in r.floors:
            head_t = float(pressure[f.takeoff])
            head_f = float(pressure[f.fixture])
            static = r.full_level - (f.story.elevation + o.takeoffHeight)
            v_seg = float(velocity[f.segment])
            v_branch = float(velocity[f.branch])
            ok_pressure = head_f >= f.required - 1e-6
            ok_static = static <= MAX_HEAD + 1e-9
            out.append(
                {
                    "story": f.story.id,
                    "name": f.story.name,
                    "riser": r.id,
                    "elevation": round(f.story.elevation, 4),
                    "units": round(f.units, 3),
                    "flow": round(f.branch_flow * 1000, 4),
                    "riserFlow": round(float(flowrate[f.segment]) * 1000, 4),
                    "takeoffElevation": round(f.story.elevation + o.takeoffHeight, 4),
                    "takeoffHead": round(head_t, 4),
                    "fixtureElevation": round(f.story.elevation + f.fixture_height, 4),
                    "head": round(head_f, 4),
                    "required": round(f.required, 4),
                    "staticHead": round(static, 4),
                    "maxHead": MAX_HEAD,
                    "velocity": round(v_seg, 4),
                    "branchVelocity": round(v_branch, 4),
                    "branchDiameter": f.branch_diameter,
                    "pressureOk": bool(ok_pressure),
                    "staticOk": bool(ok_static),
                    "ok": bool(ok_pressure and ok_static),
                }
            )
            name = f"{f.story.name} ({r.id})"
            checks.append(
                _check(
                    f"Residual head at the fixture, {name}",
                    f.required,
                    max(head_f, 0.0),
                    "m",
                    "BNBC Table 8.5.6, Sec 5.10.4.3",
                    ok=ok_pressure,
                )
            )
            checks.append(
                _check(
                    f"Static head on the fittings, {name}",
                    static,
                    MAX_HEAD,
                    "m",
                    "BNBC Sec 5.10.4.2 (Sec 5.11.1: 350 kPa)",
                )
            )
            checks.append(
                _check(
                    f"Velocity in {r.id} at {f.story.name} (Ø{r.diameter:g})",
                    v_seg,
                    limit,
                    "m/s",
                    "BNBC Sec 5.10.1(c)(ii)",
                )
            )
            checks.append(
                _check(
                    f"Velocity in the branch, {name} (Ø{f.branch_diameter:g})",
                    v_branch,
                    velocity_limit(f.branch_diameter),
                    "m/s",
                    "BNBC Sec 5.10.1(c)(ii)",
                )
            )
        _advice(r, [x for x in out if x["riser"] == r.id], notes)
    zones = _zones(risers, o, flush, notes, problems)
    return out, zones


def _advice(r: _Riser, floors: list[dict[str, Any]], notes: list[str]) -> None:
    low = [f for f in floors if not f["pressureOk"]]
    if low:
        deficit = max(f["required"] - f["head"] for f in low)
        names = ", ".join(f["name"] for f in low)
        if r.upfeed:
            notes.append(
                f"{r.id}: the main's head is short by {deficit:.2f} m at {names}: provide a "
                "ground tank and a roof tank (BNBC Sec 5.8.2, 5.8.3)."
            )
        else:
            notes.append(
                f"{r.id}: the residual head is short at {names} (by up to {deficit:.2f} m): "
                f"raise the tank {r.source} by at least {deficit:.2f} m, enlarge the riser or "
                "the branches, or feed these floors with a booster pump from the tank."
            )


def _zone_margin(
    r: _Riser, members: list[_Floor], outlet: float, o: HydraulicOptions, flush: bool
) -> tuple[float, dict[str, float]]:
    """Solve one proposed zone on its own: ``members`` fed down from a tank at the riser whose
    outlet (minimum water level) is at ``outlet`` [m]. Returns the least margin (residual head
    less the required, m) and each floor's residual head at the fixture."""
    floors = [replace(f) for f in members]
    zone = _Riser(
        f"{r.id}~zone", r.x, r.y, r.material, r.c, 0.0 if r.sized else r.diameter, r.sized,
        "zone", outlet, outlet, False, floors, start=outlet - OUTLET_ABOVE_BOTTOM,
    )  # fmt: skip
    wn = _new_network()
    _add_riser(wn, zone, o, flush, None)
    pressure = _solve(wn).node["pressure"].iloc[0]
    heads = {f.story.id: float(pressure[f.fixture]) for f in floors}
    margin = min(heads[f.story.id] - f.required for f in floors)
    return margin, heads


def _zone_members(floors: list[_Floor], full: float, o: HydraulicOptions) -> list[_Floor]:
    """From the first of ``floors`` down, those whose take-off is within 35 m of ``full``."""
    members = [floors[0]]
    for f in floors[1:]:
        if full - (f.story.elevation + o.takeoffHeight) > MAX_HEAD + 1e-9:
            break
        members.append(f)
    return members


def _zones(
    risers: list[_Riser],
    o: HydraulicOptions,
    flush: bool,
    notes: list[str],
    problems: list[str],
) -> list[dict[str, Any]]:
    """Pressure zones (BNBC Sec 5.11.1): from the source down, a new zone where the static head
    with the tank full would exceed 35 m (Sec 5.10.4.2).

    Each lower zone is fed by an intermediate tank at the riser (or a pressure reducing valve).
    Its outlet (minimum water level) is found by solving that zone as its own network (the
    zone's own flows, friction and fittings): the lowest level, rounded up to 10 mm, at which
    every fixture of the zone has the Table 8.5.6 pressure. Its top water level is the outlet
    plus the roof tank's draw-down (top water level less outlet), and the zone ends where the
    static head from that top water level would exceed 35 m."""
    zones: list[dict[str, Any]] = []
    for r in risers:
        if r.upfeed or not r.floors:
            continue
        drawdown = max(r.full_level - r.source_level, 0.0)
        first = _zone_members(r.floors, r.full_level, o)
        if len(first) == len(r.floors):
            continue
        groups: list[dict[str, Any]] = [
            {"outlet": r.source_level, "full": r.full_level, "members": first, "margin": None}
        ]
        k = len(first)
        while k < len(r.floors):
            rest = r.floors[k:]
            top = rest[0]
            outlet = top.story.elevation + top.fixture_height + top.required
            seen: list[tuple[float, int]] = []
            for _ in range(12):
                members = _zone_members(rest, outlet + drawdown, o)
                margin, _ = _zone_margin(r, members, outlet, o, flush)
                state = (outlet, len(members))
                if margin >= -1e-6 and state in seen:
                    break
                seen.append(state)
                outlet = math.ceil((outlet - margin) * 100 - 1e-6) / 100
            else:  # membership oscillating: take the higher level, which then works
                outlet = max(level for level, _ in seen)
                members = _zone_members(rest, outlet + drawdown, o)
                margin, _ = _zone_margin(r, members, outlet, o, flush)
            full = outlet + drawdown
            z_top = top.story.elevation + o.takeoffHeight
            if full - z_top > MAX_HEAD + 1e-9:
                problems.append(
                    f"{r.id}: below {top.story.name} even one floor needs more than {MAX_HEAD:g} "
                    "m of static head with a tank: use pressure reducing valves or a booster."
                )
            groups.append({"outlet": outlet, "full": full, "members": members, "margin": margin})
            k += len(members)
        for i, g in enumerate(groups):
            members = g["members"]
            lowest = min(m.story.elevation + o.takeoffHeight for m in members)
            outlet, full = g["outlet"], g["full"]
            if i == 0:
                method = f"the overhead tank {r.source}"
            else:
                above = members[0].story.name
                method = (
                    f"an intermediate tank at {r.id} above {above} with its outlet (minimum "
                    f"water level) at {outlet:.2f} m or higher, its bottom at "
                    f"{outlet - OUTLET_ABOVE_BOTTOM:.2f} m and its top water level at "
                    f"{full:.2f} m (BNBC Sec 5.11.1(a): its own down-take pipe; the floor it "
                    f"stands on fed from the zone above), or a pressure reducing valve on "
                    f"{r.id} above {above} (Sec 5.11.1(b)) set to a downstream head level of "
                    f"{outlet:.2f} m to {lowest + MAX_HEAD:.2f} m"
                )
            zones.append(
                {
                    "riser": r.id,
                    "zone": i + 1,
                    "stories": [m.story.id for m in members],
                    "names": [m.story.name for m in members],
                    "sourceLevel": round(outlet, 4),
                    "tankBottom": round(outlet - OUTLET_ABOVE_BOTTOM, 4),
                    "fullLevel": round(full, 4),
                    "lowestFitting": round(lowest, 4),
                    "maxStaticHead": round(full - lowest, 4),
                    "minMargin": None if g["margin"] is None else round(g["margin"], 4),
                    "solved": i > 0,
                    "source": method,
                }
            )
        notes.append(
            f"{r.id}: the static head exceeds {MAX_HEAD:g} m from {groups[1]['members'][0].story.name} "
            f"down: {len(groups)} pressure zones (BNBC Sec 5.11.1: intermediate tanks every 5-6 "
            "storeys, or pressure reducing valves). Each lower zone was solved on its own to "
            "place its source (with its friction and the roof tank's draw-down); the floor "
            "heads above are those of the network as entered."
        )
    return zones


def _p1_building(building: Any) -> Any:
    """The plumbing sizing's Building of 06 BIM data (an empty one when it does not parse)."""
    from saengine.plumbing.building import Building

    try:
        from saengine.library.bim import BuildingModel

        model = (
            building
            if hasattr(building, "stories")
            else BuildingModel.model_validate(_dump(building) or {})
        )
        return Building.of(model)
    except Exception:  # noqa: BLE001 - a partial model: no floor areas
        return Building()


def _pump_flow(
    plumbing: dict[str, Any] | None,
    building: Any,
    volume: float,
    o: HydraulicOptions,
    notes: list[str],
) -> tuple[float, str, float | None]:
    """The delivery pump's flow [m³/s], how it was found and the daily demand [L/day].

    BNBC Sec 5.9.1.2(c)(ii) (p. 1041): capacity of the delivery pump = the peak hourly demand.
    The flow is the plumbing sizing's (:func:`saengine.plumbing.supply.pump`, so the two
    agree): the peak hourly demand of Eq 8.5.1, or the daily demand over the contract's
    pumping hours when they are given. Without a daily demand (no occupancy or population),
    the daily demand is taken as twice the overhead volume (Sec 5.9.1.2(c)(i): the roof tank
    holds half the daily demand + the 1-hour fire reserve of a tall building; a fire reserve
    in the tank is then counted as demand: conservative)."""
    from saengine.plumbing.demand import daily_demand, peak_hourly
    from saengine.plumbing.supply import pump as delivery_pump

    if o.pumpFlow:
        return float(o.pumpFlow) / 60000, f"{o.pumpFlow:g} L/min as given", None
    model = None
    try:
        from saengine.library.mep import Plumbing

        model = Plumbing.model_validate(plumbing or {})
        daily = float(daily_demand(model, _p1_building(building))["daily"])
    except Exception:  # noqa: BLE001 - an incomplete plumbing section
        daily = 0.0
    if model is not None and daily > 0:
        found = delivery_pump(model, daily)
        return (
            float(found["flow"]) / 60000,
            f"the plumbing sizing's delivery pump: {found['note']}",
            daily,
        )
    daily = 2 * volume * 1000
    hours = float(((plumbing or {}).get("supply") or {}).get("pumpHours") or 0)
    if hours:
        flow = daily / hours / 3600 / 1000
        basis = f"twice the overhead volume ({daily / 1000:.2f} m³) in {hours:g} pumping hours"
    else:
        flow = peak_hourly(daily) / 3600 / 1000
        basis = (
            f"peak hourly demand (Sec 5.9.1.2(c)(ii), Eq 8.5.1) of a daily demand of twice the "
            f"overhead volume ({daily / 1000:.2f} m³, Sec 5.9.1.2(c)(i))"
        )
    notes.append(
        "Pump: no daily demand from the plumbing stories (occupancy and population): taken as "
        "twice the overhead tank volume, which counts any fire reserve held in it as demand."
    )
    return flow, basis, daily


def _pump(
    overhead: list[_Tank],
    underground: list[_Tank],
    raw_risers: list[dict[str, Any]],
    supply: dict[str, Any],
    o: HydraulicOptions,
    checks: list[dict[str, Any]],
    notes: list[str],
    problems: list[str],
    plumbing: dict[str, Any] | None = None,
    building: Any = None,
) -> dict[str, Any] | None:
    if not underground:
        if supply.get("source") != "mains":
            notes.append("No underground reservoir in 07 MEP: no transfer pump analysed.")
        return None
    reservoir = min(underground, key=lambda t: t.bottom)
    tank = overhead[-1]
    volume = sum(t.volume for t in overhead)
    if volume <= 0:
        problems.append(
            "The overhead tanks have no volume (length, width and water depth): no pump flow."
        )
        return None
    flow, basis, daily = _pump_flow(plumbing, building, volume, o, notes)
    main = next((r for r in raw_risers if r.get("system") == "pumpMain"), None)
    if main is not None:
        mx, my = float(main.get("x") or 0) / 1000, float(main.get("y") or 0) / 1000
        horizontal = (
            abs(reservoir.x - mx) + abs(reservoir.y - my) + abs(mx - tank.x) + abs(my - tank.y)
        )
        material, c = _material_c(main.get("material") or "GI", o)
        diameter = float(main.get("diameter") or 0)
    else:
        horizontal = abs(reservoir.x - tank.x) + abs(reservoir.y - tank.y)
        material, c = _material_c("GI", o)
        diameter = 0.0
    sized = diameter <= 0
    if sized:
        found = size_for_flow(flow, material)
        if found is None:
            problems.append("The pump main needs more than 200 mm.")
        diameter = found or 200.0
    vertical = tank.inlet - reservoir.bottom
    length = horizontal + vertical
    equivalent = length + fitting_length(diameter, PUMP_FITTINGS)
    d = diameter / 1000

    # WNTR: the reservoir at its lowest level, the pump main to the inlet drawing the flow; a
    # source head high enough at the pump gives the friction as the head difference.
    wn = _new_network()
    wn.add_reservoir("pump", base_head=tank.inlet + 100.0)
    wn.add_junction("inlet", base_demand=flow, elevation=tank.inlet)
    wn.add_pipe("main", "pump", "inlet", length=equivalent, diameter=d, roughness=c)
    res = _solve(wn)
    friction = tank.inlet + 100.0 - float(res.node["head"].iloc[0]["inlet"])
    velocity = float(res.link["velocity"].iloc[0]["main"])
    static = tank.inlet - reservoir.bottom
    velocity_head = velocity**2 / (2 * G)
    tdh = static + friction + velocity_head + o.inletResidual
    hydraulic = RHO * G * flow * tdh / 1000  # kW
    shaft = hydraulic / o.pumpEfficiency
    checks.append(
        _check(
            f"Velocity in the pump main (Ø{diameter:g})",
            velocity,
            velocity_limit(diameter),
            "m/s",
            "BNBC Sec 5.10.1(c)(ii)",
        )
    )
    return {
        "reservoir": reservoir.id,
        "tank": tank.id,
        "volume": round(volume, 4),
        "daily": None if daily is None else round(daily / 1000, 4),  # m³/day
        "pumpingHours": None if not daily else round(daily / 1000 / (flow * 3600), 4),
        "flowBasis": basis,
        "flow": round(flow * 1000, 4),  # L/s
        "flowM3h": round(flow * 3600, 4),
        "diameter": diameter,
        "sized": sized,
        "material": material,
        "hazenC": c,
        "length": round(length, 4),
        "equivalentLength": round(equivalent, 4),
        "velocity": round(velocity, 4),
        "reservoirLevel": round(reservoir.bottom, 4),
        "inletLevel": round(tank.inlet, 4),
        "staticLift": round(static, 4),
        "friction": round(friction, 4),
        "velocityHead": round(velocity_head, 4),
        "residual": o.inletResidual,
        "tdh": round(tdh, 4),
        "efficiency": o.pumpEfficiency,
        "hydraulicPower": round(hydraulic, 4),
        "shaftPower": round(shaft, 4),
        "horsepower": round(shaft / 0.7457, 4),
        "motor": motor_rating(shaft),
        "note": (
            "BNBC Sec 5.10.5: H = hs + hd + hf + hv (eq. 8.5.3 velocity head) plus the inlet's "
            f"residual; P = ρgQH/η (eq. 8.5.2 in SI); flow: {basis}; the reservoir at its "
            "inside bottom."
        ),
    }


def _mains(
    supply: dict[str, Any],
    ground: float,
    stories: list[_Story],
    underground: list[_Tank],
    overhead: list[_Tank],
    o: HydraulicOptions,
    required: float,
    checks: list[dict[str, Any]],
    problems: list[str],
    notes: list[str] | None = None,
) -> dict[str, Any] | None:
    """The city main's checks. With an underground reservoir the building has the Sec 5.8.3
    system (the main fills the reservoir, a pump lifts the water to the roof tank), so feeding
    the fixtures or the roof tank straight from the main (Sec 5.8.1, 5.8.2) is only an option:
    those heads are reported (``directFloors``, ``roofTank`` with ``applies: false``) but are
    not checks."""
    if supply.get("mainsHead") is None:
        problems.append("Supply from the city main: give its residual head at the connection.")
        return None
    head = float(supply["mainsHead"])
    residual = float(supply.get("minResidualHead") or REQUIRED_KPA / KPA_PER_M)
    out: dict[str, Any] = {"head": head, "connectionLevel": round(ground, 4)}
    if underground:
        inlet = max(t.inlet for t in underground)
        need = inlet - ground + residual
        out["reservoir"] = {
            "inletLevel": round(inlet, 4),
            "required": round(need, 4),
            "ok": head >= need - 1e-9,
        }
        checks.append(
            _check(
                "City main fills the underground reservoir",
                need,
                head,
                "m",
                "BNBC Sec 5.8.3 (through a ball valve); service-pipe friction not included",
            )
        )
    direct = [
        s
        for s in stories
        if s.elevation >= ground - 1e-9
        and head - (s.elevation + o.fixtureHeight - ground) >= required - 1e-9
    ]
    out["directFloors"] = [s.id for s in direct]
    pumped = bool(underground)
    out["system"] = "reservoirAndPump" if pumped else "mains"
    if pumped and notes is not None:
        notes.append(
            "Supply: the city main fills the underground reservoir and a pump lifts the water to "
            "the roof tank (BNBC Sec 5.8.3), so the main need not feed the fixtures or the roof "
            "tank directly (Sec 5.8.1, 5.8.2 apply only with sufficient pressure); those heads "
            "are reported, not checked."
        )
    lowest = next((s for s in stories if s.elevation >= ground - 1e-9), None)
    if lowest is not None and not pumped:
        need = lowest.elevation + o.fixtureHeight - ground + required
        checks.append(
            _check(
                f"City main feeds {lowest.name} directly",
                need,
                head,
                "m",
                "BNBC Sec 5.8.1 (static; peak friction not included)",
            )
        )
    if overhead:
        inlet = overhead[-1].inlet
        need = inlet - ground + residual
        out["roofTank"] = {
            "inletLevel": round(inlet, 4),
            "required": round(need, 4),
            "ok": head >= need - 1e-9,
            "applies": not pumped,
        }
        if pumped:
            return out
        checks.append(
            _check(
                "City main fills the roof tank (balancing tank)",
                need,
                head,
                "m",
                "BNBC Sec 5.8.2; otherwise a ground tank and a pump, Sec 5.8.3; "
                "no pumping from the main (Sec 5.8.1)",
            )
        )
    return out

"""BNBC 2020 Part 8 Chapter 1 (Electrical and Electronic Engineering Services for Buildings)
as data, and the typical equipment data the proposals use.

Every BNBC number here was transcribed from the page cited (the page of
``bnbc-2020-part2.pdf``; the tables were read from the rendered pages). Numbers that are not
BNBC's are marked: "SAEngine practice" (a stated assumption the engineer can change in 07 MEP)
or "typical" (manufacturers' catalogue ranges for the first layout, to be replaced with the
selected unit's data).
"""

from __future__ import annotations

from dataclasses import dataclass

# ─────────────────────────────────────── sources ───────────────────────────────────────

PAGES = {
    "1.3.2": "BNBC 2020 Part 8 Sec 1.3.2 (p763-764)",
    "8.1.17": "BNBC 2020 Part 8 Table 8.1.17, Sec 1.3.2.5 (p765-767)",
    "8.A.1": "BNBC 2020 Part 8 Appendix A Table 8.A.1 (p1167-1168)",
    "1.3.13.1": "BNBC 2020 Part 8 Sec 1.3.13.1 (p790-791)",
    "1.3.13.2": "BNBC 2020 Part 8 Sec 1.3.13.2 (p791)",
    "1.3.13.3": "BNBC 2020 Part 8 Sec 1.3.13.3 (p792)",
    "1.3.18.1": "BNBC 2020 Part 8 Sec 1.3.18.1 (p796)",
    "1.3.18.2": "BNBC 2020 Part 8 Sec 1.3.18.2 (p796-797)",
    "1.3.18.3": "BNBC 2020 Part 8 Sec 1.3.18.3 (p797-798)",
    "8.1.23": "BNBC 2020 Part 8 Table 8.1.23 (p798)",
    "1.3.18.4": "BNBC 2020 Part 8 Sec 1.3.18.4 (p799)",
    "1.3.18.6": "BNBC 2020 Part 8 Sec 1.3.18.6 (p799)",
    "1.3.18.7": "BNBC 2020 Part 8 Sec 1.3.18.7 (p800)",
    "1.3.19.2": "BNBC 2020 Part 8 Sec 1.3.19.2 (p801)",
    "1.3.19.3": "BNBC 2020 Part 8 Sec 1.3.19.3 (p801)",
    "8.1.24": "BNBC 2020 Part 8 Table 8.1.24 (p802)",
    "1.3.20.1": "BNBC 2020 Part 8 Sec 1.3.20.1(e) (p805)",
    "1.3.32.7": "BNBC 2020 Part 8 Sec 1.3.32.7 (p818-819)",
    "1.3.32.10": "BNBC 2020 Part 8 Sec 1.3.32.10 (p820)",
    "8.1.27": "BNBC 2020 Part 8 Table 8.1.27(a)-(c), Sec 1.3.33.5 (p821-823)",
    "8.1.28": "BNBC 2020 Part 8 Table 8.1.28 (p824)",
    "1.3.33.6": "BNBC 2020 Part 8 Sec 1.3.33.6 (p823, p825)",
    "1.3.33.7": "BNBC 2020 Part 8 Sec 1.3.33.7 (p825)",
    "1.3.33.8": "BNBC 2020 Part 8 Sec 1.3.33.8 (p826-828)",
    "8.1.29": "BNBC 2020 Part 8 Table 8.1.29 (p827)",
    "8.1.1": "BNBC 2020 Part 8 Eq 8.1.1, Sec 1.3.33.8(g) (p828)",
    "4.2.1": "BNBC 2020 Part 8 Sec 4.2.1.1, 4.2.1.3 (p982-983)",
}

# ─────────────────────────────── Table 8.1.17: load densities ───────────────────────────────


@dataclass(frozen=True)
class Use:
    """A row of Table 8.1.17: the minimum unit load [W/m²] without and with air conditioning
    (None: the table gives none, '-')."""

    key: str
    label: str
    non_ac: float
    ac: float | None
    #: Table 8.1.27(a) index A (use of structure) and (b) index C (contents) of the row's kind
    #: of building, the lightning risk assessment's default for a story of this use.
    lightning_a: int
    lightning_c: int


#: BNBC 2020 Part 8 Table 8.1.17 Minimum Load Densities (p766-767).
USES: dict[str, Use] = {
    u.key: u
    for u in (
        Use("residenceSingle", "Residence/dwelling: single family", 20, 75, 2, 2),
        Use("residenceMulti", "Residence/dwelling: multi-family (other than hotels)", 20, 75, 7, 2),
        Use("hospital", "Hospitals", 32, 80, 10, 10),
        Use("hotel", "Hotels, including apartment house (no electric cooking)", 24, 75, 7, 2),
        Use("office", "Office and commercial multi-storeyed buildings", 28, 75, 7, 2),
        Use("industrial", "Industrial building (excluding the loads for machines)", 16, None, 6, 2),
        Use("departmentStore", "Departmental stores", 28, 75, 8, 10),
        Use("bank", "Banks", 20, 75, 7, 2),
        Use("restaurant", "Restaurants (no electric cooking)", 16, 75, 8, 10),
        Use("barber", "Barber shops and beauty parlours", 32, 75, 7, 2),
        Use("school", "Schools and colleges", 12, 70, 10, 10),
        Use("parking", "Parking area in commercial buildings", 4, None, 7, 2),
        Use("warehouse", "Warehouses, large storage areas", 2, None, 6, 2),
    )
}
USE_KEYS = tuple(USES)

#: Sec 1.3.18.1 (p796): "a load factor of at least 80% shall be applied to the estimated load
#: of the building" to determine the rating of the substation.
LOAD_FACTOR = 0.8
#: Sec 1.3.18.1 (p796) and Sec 1.3.20.1(e) (p805): an 11 kV/0.4 kV substation (HT supply) for a
#: building whose load exceeds 50 kW ("connected loads of 50 kW and above").
SUBSTATION_KW = 50.0
#: Power factor of the building's demand (BNBC 2020 Part 8 gives none): SAEngine practice,
#: editable in 07 MEP (electrical.supply.powerFactor).
POWER_FACTOR = 0.85
#: The LT system voltage, line to line [V] (0.4 kV, Sec 1.3.18).
LT_VOLTAGE = 400.0

# ───────────────────────── Sec 1.3.18: substation and transformer rooms ─────────────────────────

#: Sec 1.3.18.3(a) (p797): the minimum height of a substation room, 3.0 m to 3.6 m depending on
#: the size of the transformer [mm].
SUBSTATION_HEIGHT = (3000.0, 3600.0)
#: Sec 1.3.18.3(b) (p797): minimum spacing between the transformer periphery and walls [mm].
TRANSFORMER_CLEARANCE = {"twoWalls": 750.0, "threeWalls": 1000.0, "enclosed": 1250.0}
#: ... and between transformers in a room: 11 kV, higher voltage [mm].
TRANSFORMER_SPACING = {"11kV": 1500.0, "33kV": 2500.0}
#: Sec 1.3.18.3(c) (p798): oil content above which a soak pit is to be provided [litres].
SOAK_PIT_OIL = 2000.0

#: Table 8.1.23 (p798): (number, kVA) -> (transformer area, total substation area with HT, LT
#: panels and transformer room, without generators) [m²].
SUBSTATION_AREAS: dict[tuple[int, int], tuple[float, float]] = {
    (1, 150): (12, 45),
    (1, 250): (13, 48),
    (2, 250): (26, 100),
    (1, 400): (13, 48),
    (2, 400): (30, 100),
    (3, 400): (40, 135),
    (2, 630): (26, 100),
    (3, 630): (40, 190),
    (2, 1000): (40, 180),
    (3, 1000): (45, 220),
}

#: Distribution transformer ratings [kVA]: those of Table 8.1.23 (150, 250, 400, 630, 1000) and
#: the IEC 60076 preferred ratings (from memory, to be checked).
TRANSFORMER_SIZES = (
    100, 150, 160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500,
)  # fmt: skip
#: The largest unit SAEngine proposes before splitting the load between units (SAEngine practice).
TRANSFORMER_MAX = 1600

# ─────────────────────────── Sec 1.3.19: standby generator ───────────────────────────

#: Sec 1.3.19.2 (p801): minimum spacing between the generator periphery and walls in an
#: enclosed room, and between generators [mm].
GENERATOR_CLEARANCE = 1000.0
GENERATOR_SPACING = 1250.0
#: Table 8.1.24 (p802): generator capacity [kW] -> recommended room area [m²] (one set).
GENERATOR_AREAS: dict[int, float] = {25: 20, 48: 24, 100: 30, 150: 36, 300: 48, 500: 56}

#: Standby generating set ratings [kVA] (typical catalogue sizes, from memory, to be checked).
GENERATOR_SIZES = (
    20, 30, 40, 50, 62.5, 80, 100, 125, 160, 200, 250, 320, 400, 500, 625, 750, 1000, 1250, 1500,
)  # fmt: skip
#: Rated power factor of a generating set (kW = 0.8 kVA; ISO 8528 rating basis, from memory).
GENERATOR_PF = 0.8
#: Specific fuel consumption of a diesel set at full load [l/kWh] (typical, from memory).
FUEL_RATE = 0.27
#: Hours of running the fuel tank holds (BNBC 2020 Part 8 gives none): SAEngine practice,
#: editable in 07 MEP (electrical.supply.fuelHours).
FUEL_HOURS = 8.0
#: Share of the lighting and power load that is essential (Sec 1.3.19.2 lists essential
#: lighting, air conditioning, equipment and services without a number): SAEngine practice,
#: editable (electrical.supply.essentialShare).
ESSENTIAL_SHARE = 0.25
#: Diesel: density [kg/m³] (typical 820-860).
DIESEL_DENSITY = 840.0
#: Mineral transformer oil: density [kg/m³] (typical 870-890; from memory, to be checked).
TRANSFORMER_OIL_DENSITY = 880.0
G = 9.81

#: Sec 4.2.1.1 (p982): lifts in buildings more than six storeys or 20 m high; Sec 4.2.1.3:
#: standby power for one or more lifts in a building of more than ten storeys or above 32 m,
#: and in hospitals and health care buildings.
LIFT_STOREYS, LIFT_HEIGHT = 6, 20.0
LIFT_STANDBY_STOREYS, LIFT_STANDBY_HEIGHT = 10, 32.0

# ─────────────────────────── Sec 1.3.13: shafts and rising mains ───────────────────────────

#: Sec 1.3.13.1 (p790): buildings over six storeys or 20 m: at least one vertical electrical
#: service shaft of 200 mm x 400 mm for every 1500 m² of floor area.
SHAFT_STOREYS, SHAFT_HEIGHT = 6, 20.0
SHAFT_SIZE = (200.0, 400.0)
SHAFT_AREA = 1500.0
#: Sec 1.3.13.2(a) (p791): five storeys or fewer with less than 600 m² a floor: PVC cables in
#: PVC or GI pipes may serve as risers; (d) more than nine storeys: busbar trunking preferred.
CABLE_RISER_STOREYS, CABLE_RISER_AREA = 5, 600.0
BUSBAR_STOREYS = 9
#: Sec 1.3.13.2(e) (p791): riser cables fixed on the wall with 37 mm between adjacent cables.
CABLE_SPACING = 37.0
#: Sec 1.3.13.3(a) (p792): feeder busbar trunking typically 200 A to 3000 A.
BUSBAR_RANGE = (200.0, 3000.0)

#: Clearance round a riser or tray in its opening, each side [mm], and the size step (SAEngine
#: practice: BNBC 1.3.13.1 asks the space left round the cables to be filled with RCC or a
#: non-combustible material, which needs room to place it).
OPENING_CLEARANCE = 100.0
TRAY_CLEARANCE = 50.0
OPENING_STEP = 50.0
#: Space above a cable tray for laying the cables [mm] (SAEngine practice).
TRAY_HEADROOM = 150.0
#: Fill of a cable tray's cross-section by the cables (40 %, the usual limit for multicore power
#: cables; from memory, to be checked against the tray maker's data).
TRAY_FILL = 0.4
#: Standard cable tray widths [mm] (typical).
TRAY_WIDTHS = (100, 150, 200, 300, 450, 600, 750, 900)

# ─────────────────────────── Sec 1.3.32-1.3.33: earthing, lightning ───────────────────────────

#: Sec 1.3.32.7 (p818): the resistance of the earthing system "shall be around one ohm".
SYSTEM_EARTH_OHM = 1.0
#: Sec 1.3.32.7(e) (p819): multiple electrodes not less than 1.8 m apart [mm].
ELECTRODE_SPACING = 1800.0
#: Sec 1.3.32.10 (p820): minimum inside dimension of an earthing pit [mm].
EARTH_PIT = 600.0
#: Sec 1.3.33.8(b) (p826): lightning earth resistance, up to 10 storeys and high rise [ohm].
LIGHTNING_EARTH_OHM = {"upTo10": 10.0, "highRise": 2.0}

#: Table 8.1.27(a) Index B: type of construction (p821).
CONSTRUCTION = {
    "steelNonmetalRoof": ("Steel framed encased with nonmetal roof", 1),
    "rcNonmetalRoof": ("Reinforced concrete with nonmetal roof", 2),
    "masonry": ("Brick, plain concrete or masonry with nonmetal roof", 4),
    "metalRoof": ("Steel framed encased or reinforced concrete with metal roof", 5),
    "timber": ("Timber framed or clad, roof other than metal or thatch", 7),
    "thatch": ("Any building with a thatched roof", 10),
}
#: Table 8.1.27(a) Index A: use of structure (p821).
STRUCTURE_USE = {
    "house": ("Houses and similar buildings", 2),
    "houseAerial": ("Houses and similar buildings with outside aerial", 4),
    "factory": ("Small and medium size factories, workshops and laboratories", 6),
    "large": ("Big industrial plants, telephone exchanges, office blocks, hotels, flats", 7),
    "assembly": ("Places of assembly, department stores, stations, airports, stadiums", 8),
    "school": ("Schools, hospitals, children's homes and other such structures", 10),
}
#: Table 8.1.27(b) Index C: contents or consequential effects (p822).
CONTENTS = {
    "ordinary": ("Ordinary domestic or office building, factories, workshops", 2),
    "susceptible": ("Industrial and agricultural buildings with specially susceptible contents", 5),
    "power": ("Power stations, gas works, telephone exchanges, radio stations", 6),
    "key": ("Industrial key plants, ancient monuments, historic buildings, museums", 8),
    "people": ("Schools, hospitals, children's and other homes, places of assembly", 10),
}
#: Table 8.1.27(b) Index D: degree of isolation (p822).
ISOLATION = {
    "builtUp": ("In a large area of structures or trees of similar or greater height", 2),
    "few": ("In an area with a few other structures or trees of similar height", 5),
    "isolated": ("Completely isolated or at least twice the height of its surroundings", 10),
}
#: Table 8.1.27(b) Index E: type of terrain (p822).
TERRAIN = {
    "flat": ("Flat terrain at any level", 2),
    "hilly": ("Hilly terrain", 6),
    "mountainous": ("Mountainous terrain 300 m and above", 8),
}
#: Table 8.1.27(c) Index F: height of structure, (upper bound m, index) (p822).
HEIGHT_INDEX = ((9, 2), (15, 4), (18, 5), (24, 8), (30, 11), (38, 16), (46, 22), (53, 30))
#: Table 8.1.27(c) Index G: thunderstorm days a year, (upper bound, index); over 21: 21 (p822).
THUNDER_INDEX = ((3, 2), (6, 5), (9, 8), (12, 11), (15, 14), (18, 17), (21, 20))
THUNDER_OVER = 21
#: The thunderstorm index BNBC's own examples of Table 8.1.28 (p824) use for Bangladesh.
THUNDER_DEFAULT = 21
#: Sec 1.3.33.5 (p823): the marginal risk index; Table 8.1.27(c) note c: structures higher
#: than 53 m require protection in all cases.
MARGINAL_RISK = 40
ALWAYS_HEIGHT = 53.0

#: Sec 1.3.33.7 (p825): at least one air spike for every 80 m² of roof to begin with.
SPIKE_AREA = 80.0
#: Sec 1.3.33.6(a) (p825): an air terminal at least 300 mm above the highest point [mm].
SPIKE_HEIGHT = 300.0
#: Sec 1.3.33.8(a) (p826): no part of the roof more than 9 m from the nearest horizontal
#: conductor (+0.3 m for each 0.3 m the part is below the conductor) [mm].
ROOF_CONDUCTOR_REACH = 9000.0
#: Sec 1.3.33.8(c) (p827): one down conductor for a base area up to 100 m²; else one for the
#: first 80 m² and one more for every 100 m² or part thereof; or one for every 30 m of
#: perimeter.
DOWN_SINGLE_AREA = 100.0
DOWN_FIRST_AREA = 80.0
DOWN_STEP_AREA = 100.0
DOWN_PERIMETER = 30000.0
#: Sec 1.3.33.6(e) (p825): an earth inspection box for each down conductor 1000 mm above the
#: plinth level.
TEST_BOX_HEIGHT = 1000.0
#: Table 8.1.29 (p827): minimum sizes of the components.
LIGHTNING_SIZES = {
    "airTerminal": "copper rod 12 mm dia (copper strip 20 x 3 mm; stranded PVC copper cable "
    "19 strands of 1.8 mm dia)",
    "downConductor": "copper strip 20 x 3 mm or stranded PVC copper cable 19 x 1.8 mm dia",
    "earthElectrode": "copper rod 12 mm dia; copper-clad steel 50 mm dia; GI pipe 38/50 mm dia",
}

#: IEC 62305-3 (BNBC 2020 Part 8 does not use protection levels; it allows the rolling sphere
#: method of NFPA 780, Sec 1.3.33.8(j)): level -> (rolling sphere radius m, mesh size m,
#: typical down-conductor spacing m). From memory, to be checked against IEC 62305-3 Tables 2
#: and 4.
IEC_LEVELS = {
    "I": (20.0, 5.0, 10.0),
    "II": (30.0, 10.0, 10.0),
    "III": (45.0, 15.0, 15.0),
    "IV": (60.0, 20.0, 20.0),
}
#: IEC 62305-3: reinforcement used as a natural down conductor when its overall resistance from
#: the top to ground level is at most 0.2 ohm (from memory, to be checked).
REBAR_OHM = 0.2

# ─────────────────────────── typical equipment (replace with the unit's data) ───────────────────

TYPICAL = "typical, replace with the selected unit's data"

#: Oil-immersed 11/0.4 kV distribution transformer: kVA -> (length, width, height mm, total
#: mass kg, oil litres). Typical catalogue ranges, from memory, to be checked.
TRANSFORMER_OIL = {
    100: (1200, 800, 1300, 750, 250),
    150: (1250, 830, 1330, 900, 290),
    160: (1300, 850, 1350, 950, 300),
    200: (1350, 900, 1400, 1100, 350),
    250: (1400, 950, 1450, 1300, 400),
    315: (1450, 1000, 1500, 1500, 450),
    400: (1550, 1050, 1600, 1800, 550),
    500: (1650, 1100, 1650, 2100, 650),
    630: (1750, 1150, 1750, 2500, 750),
    800: (1850, 1200, 1850, 3000, 900),
    1000: (1950, 1250, 1950, 3500, 1050),
    1250: (2050, 1350, 2050, 4200, 1250),
    1600: (2200, 1450, 2150, 5000, 1500),
    2000: (2350, 1550, 2250, 6000, 1800),
    2500: (2500, 1650, 2350, 7200, 2100),
}
#: Cast resin dry-type: mass relative to the oil type's (typical, from memory).
DRY_MASS = 0.9

#: Diesel generating set on its base frame (open set, base fuel tank empty): kVA -> (length,
#: width, height mm, mass kg). Typical, from memory, to be checked.
GENERATOR_SETS = {
    20: (1700, 800, 1200, 700),
    30: (1900, 850, 1250, 850),
    40: (2000, 880, 1300, 1000),
    50: (2100, 900, 1350, 1100),
    62.5: (2200, 950, 1400, 1250),
    80: (2400, 980, 1500, 1450),
    100: (2600, 1000, 1600, 1600),
    125: (2800, 1050, 1650, 1900),
    160: (3000, 1100, 1750, 2300),
    200: (3200, 1200, 1800, 2700),
    250: (3300, 1250, 1900, 3000),
    320: (3500, 1400, 2000, 3600),
    400: (3800, 1500, 2100, 4300),
    500: (4100, 1600, 2200, 5200),
    625: (4400, 1700, 2300, 6200),
    750: (4700, 1800, 2350, 7300),
    1000: (5200, 2000, 2400, 9500),
    1250: (5800, 2100, 2500, 11500),
    1500: (6200, 2200, 2600, 13500),
}

#: Copper sandwich busbar trunking: rating A -> (width, depth mm, mass kg/m). Typical, from
#: memory, to be checked.
BUSBARS = {
    250: (130, 110, 9),
    400: (130, 110, 11),
    630: (150, 110, 16),
    800: (170, 110, 19),
    1000: (190, 110, 23),
    1250: (230, 110, 29),
    1600: (290, 110, 37),
    2000: (350, 110, 46),
    2500: (430, 110, 58),
    3200: (590, 110, 75),
}

#: 4-core XLPE/PVC copper cable outside diameter by the current it carries: (A, mm). Typical,
#: from memory, to be checked.
CABLE_OD = (
    (32, 17), (42, 19), (57, 22), (75, 26), (100, 30), (125, 34), (150, 38), (190, 42),
    (230, 47), (270, 52), (310, 57), (360, 62), (420, 68),
)  # fmt: skip

#: LT (low voltage) switchboard: a section's width and depth, height [mm]; mass per metre of
#: length [kg/m]; amperes per section beyond the incomer (typical).
LT_PANEL = {"section": 800.0, "depth": 1000.0, "height": 2200.0, "massPerM": 600.0,
            "ampsPerSection": 800.0}  # fmt: skip
#: 11 kV switchgear (VCB or RMU) panel: width, depth, height mm, mass kg (typical).
HT_PANEL = (600.0, 1200.0, 2200.0, 450.0)
#: Capacitor bank panel: width, depth, height mm, mass kg, kvar it holds (typical).
CAPACITOR_PANEL = (800.0, 800.0, 2200.0, 400.0, 300.0)
#: Target power factor of the correction (typical requirement of the distribution companies;
#: from memory, to be checked).
TARGET_PF = 0.95
#: UPS: mass kg per kVA of the cabinet; VRLA battery mass kg per kWh stored (typical).
UPS_KG_PER_KVA = 6.0
BATTERY_KG_PER_KWH = 30.0
UPS_AUTONOMY_MIN = 15.0
#: Steel fuel tank: plate thickness [mm] and steel unit weight [kN/m³].
TANK_PLATE = 5.0
STEEL_WEIGHT = 78.5


def cite(key: str, clause: str = "") -> str:
    """The source of ``key`` with a sub-clause, e.g. cite('1.3.18.7', '(g)') ->
    'BNBC 2020 Part 8 Sec 1.3.18.7(g) (p800)'."""
    source = PAGES[key]
    if not clause:
        return source
    i = source.rfind(" (p")
    return source[:i] + clause + source[i:] if i >= 0 else source + clause


def next_size(value: float, sizes: tuple[float, ...] | list[float]) -> float | None:
    """The smallest size of ``sizes`` (ascending) at least ``value`` (None above the largest)."""
    for size in sorted(sizes):
        if size >= value - 1e-9:
            return float(size)
    return None


def height_index(height_m: float) -> int | None:
    """Table 8.1.27(c) index F; None above 53 m (protection required in all cases)."""
    for bound, index in HEIGHT_INDEX:
        if height_m <= bound + 1e-9:
            return index
    return None


def thunder_index(days: float) -> int:
    """Table 8.1.27(c) index G for the thunderstorm days a year."""
    for bound, index in THUNDER_INDEX:
        if days <= bound + 1e-9:
            return index
    return THUNDER_OVER


def cable_od(amps: float) -> float:
    """Outside diameter of a 4-core copper cable for ``amps`` (typical)."""
    for limit, od in CABLE_OD:
        if amps <= limit:
            return float(od)
    return float(CABLE_OD[-1][1])

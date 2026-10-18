"""BNBC 2020 Part 8 (and the few Part 3 and Part 4 values Part 8 refers to) as data.

Every value is transcribed from the rendered page of the Bangladesh Gazette edition of
11 February 2021 (``bnbc-2020-part2.pdf`` for Parts 7 to 10, ``bnbc-2020-part1.pdf`` for
Parts 1 to 6); ``PAGES`` gives the PDF page of each table. Values marked "SAEngine" in their
comment are not BNBC's: they are documented assumptions where the code is silent.

Units: litres, mm, m², l/min, l/m²/day and lpcd (litres per capita per day) as the tables give
them.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Where each table or clause is (PDF page of the Gazette edition).
PAGES: dict[str, str] = {
    "8.5.1(a)": "Part 8 Table 8.5.1(a), part2 p1034",
    "8.5.1(b)": "Part 8 Table 8.5.1(b), part2 p1035",
    "8.5.1(c)": "Part 8 Table 8.5.1(c), part2 p1035",
    "8.5.1(d)": "Part 8 Table 8.5.1(d), part2 p1036-1037",
    "5.6.3": "Part 8 Sec 5.6.3-5.6.4, part2 p1039",
    "5.9.1.2": "Part 8 Sec 5.9.1.2(c), part2 p1041",
    "5.9.2.1": "Part 8 Sec 5.9.2.1, part2 p1042",
    "5.9.2.3": "Part 8 Sec 5.9.2.3, part2 p1043",
    "8.5.2": "Part 8 Table 8.5.2, part2 p1042",
    "8.5.3": "Part 8 Table 8.5.3, part2 p1042",
    "8.5.1": "Part 8 Eq 8.5.1 (Sec 5.10.1(a)), part2 p1043",
    "5.10.1": "Part 8 Sec 5.10.1(c)(ii), part2 p1044",
    "8.5.4": "Part 8 Table 8.5.4, part2 p1045",
    "8.5.5": "Part 8 Table 8.5.5, part2 p1046",
    "8.5.6": "Part 8 Table 8.5.6, part2 p1047",
    "5.10.4.2": "Part 8 Sec 5.10.4.2, part2 p1047",
    "5.11.1": "Part 8 Sec 5.11.1, part2 p1049",
    "8.5.7": "Part 8 Table 8.5.7, part2 p1051",
    "8.O.1": "Part 8 Appendix O Table 8.O.1, part2 p1196",
    "O": "Part 8 Appendix O Sec O.3-O.4, part2 p1195",
    "8.6.2": "Part 8 Table 8.6.2, part2 p1087",
    "6.9.3": "Part 8 Sec 6.9.3(a), part2 p1090",
    "6.9.12": "Part 8 Sec 6.9.12.7-6.9.12.13, part2 p1106",
    "8.6.8": "Part 8 Table 8.6.8, part2 p1106",
    "6.9.13": "Part 8 Sec 6.9.13.2, part2 p1107",
    "8.6.9": "Part 8 Table 8.6.9 (Sec 6.9.14), part2 p1108",
    "6.9.15": "Part 8 Sec 6.9.15.2-6.9.15.4, part2 p1108-1109",
    "8.6.10": "Part 8 Table 8.6.10, part2 p1110",
    "8.6.12": "Part 8 Table 8.6.12, part2 p1112-1113",
    "8.6.13": "Part 8 Table 8.6.13, part2 p1113",
    "6.10.2": "Part 8 Sec 6.10.2.1, part2 p1113",
    "8.6.14": "Part 8 Table 8.6.14, part2 p1114",
    "8.6.15": "Part 8 Table 8.6.15, part2 p1115",
    "8.6.16": "Part 8 Table 8.6.16, part2 p1116-1117",
    "8.6.17": "Part 8 Table 8.6.17, part2 p1118",
    "7.4.1": "Part 8 Sec 7.4.1, part2 p1129",
    "7.8.4": "Part 8 Sec 7.8.4, part2 p1132",
    "7.8.9": "Part 8 Sec 7.8.9, part2 p1134",
    "7.8.10": "Part 8 Sec 7.8.10 and 7.21.1, part2 p1134 and p1141",
    "8.7.2": "Part 8 Table 8.7.2, part2 p1135",
    "8.7.3": "Part 8 Table 8.7.3, part2 p1136",
    "7.17": "Part 8 Sec 7.17, part2 p1140",
    "8.7.4": "Part 8 Table 8.7.4, part2 p1141",
    "R": "Part 8 Appendix R Figure 8.R.1, part2 p1213",
    "S": "Part 8 Appendix S Eq 8.S.1 and Table 8.S.1, part2 p1214-1215",
    "4.4.1": "Part 4 Table 4.4.1 (Sec 4.2.1), part1 p322",
    "3:2.4.4": "Part 3 Sec 2.4.4, part1 p94",
}

# ───────────────────────────── Table 8.5.1: water consumption ─────────────────────────────


@dataclass(frozen=True)
class Occupancy:
    """One row of Tables 8.5.1(a)-(d): the per-capita water requirement of an occupancy."""

    key: str
    label: str
    table: str  # "8.5.1(a)" ...
    row: str  # the row's category as printed, e.g. "y1", "E1"
    full: float | None  # lpcd, full facility; None where the table prints "---"
    restricted: float | None  # lpcd, restricted facility
    group: str  # BNBC Part 3 occupancy group, e.g. "A3", "E1"
    unit: str = "person"  # what the population counts: person, bed, seat


#: Tables 8.5.1(a)-(d). Residential rows use the occupancy group the Part 3 classification
#: gives the building type (A1 single family, A3 flats); the table's category letters are
#: in ``row``. Where a table gives a range (8.5.1(c)), the upper value is used.
OCCUPANCIES: dict[str, Occupancy] = {
    o.key: o
    for o in (
        # Table 8.5.1(a): Metropolitan cities, city corporation areas, district towns.
        Occupancy(
            "singleFamily",
            "Single family dwelling, high income (city)",
            "8.5.1(a)",
            "A1",
            260,
            200,
            "A1",
        ),
        Occupancy(
            "apartmentLarge",
            "Big apartment > 2500 sft, high income (city)",
            "8.5.1(a)",
            "A3",
            200,
            150,
            "A3",
        ),
        Occupancy(
            "residentialFlat",
            "Moderate apartment < 2000 sft, middle income (city)",
            "8.5.1(a)",
            "y1",
            180,
            135,
            "A3",
        ),
        Occupancy(
            "apartmentSmall", "Small apartment < 1500 sft (city)", "8.5.1(a)", "y2", None, 120, "A3"
        ),
        Occupancy(
            "staffQuarter", "Junior staff flat < 1000 sft (city)", "8.5.1(a)", "z1", None, 80, "A3"
        ),
        # Table 8.5.1(b): Pourashavas, upazilas, urban growth centres.
        Occupancy(
            "townSingleFamily", "Single family dwelling (town)", "8.5.1(b)", "A1", None, 150, "A1"
        ),
        Occupancy(
            "townApartment",
            "Moderate apartment < 2000 sft (town)",
            "8.5.1(b)",
            "A3",
            None,
            135,
            "A3",
        ),
        Occupancy(
            "townSmallApartment",
            "Small apartment < 1500 sft (town)",
            "8.5.1(b)",
            "A3",
            None,
            120,
            "A3",
        ),
        Occupancy(
            "townStaffQuarter",
            "Junior staff flat < 1000 sft (town)",
            "8.5.1(b)",
            "z1",
            None,
            80,
            "A3",
        ),
        # Table 8.5.1(c): village areas (non-piped), upper value of the range.
        Occupancy("villagePrivate", "Village, private source", "8.5.1(c)", "z1", None, 60, "A1"),
        Occupancy("villagePublic", "Village, public source", "8.5.1(c)", "z2", None, 50, "A1"),
        # Table 8.5.1(d): other occupancies.
        Occupancy(
            "dormitory", "Mess, boarding house, dormitory, hostel", "8.5.1(d)", "A4", 135, 70, "A4"
        ),
        Occupancy(
            "hotel", "Hotel, lodging house (per bed)", "8.5.1(d)", "A5", 300, 135, "A5", "bed"
        ),
        Occupancy("school", "Educational up to higher secondary", "8.5.1(d)", "B1", 70, 45, "B1"),
        Occupancy(
            "college", "Training and above higher secondary", "8.5.1(d)", "B2", 100, 70, "B2"
        ),
        Occupancy("preschool", "Pre-school", "8.5.1(d)", "B3", 50, 35, "B3"),
        Occupancy(
            "childCare", "Institution for care of children", "8.5.1(d)", "C1", 180, 100, "C1"
        ),
        Occupancy(
            "custodialCapable",
            "Custodial institution, capable adults",
            "8.5.1(d)",
            "C2",
            180,
            100,
            "C2",
        ),
        Occupancy(
            "custodialIncapable",
            "Custodial institution, incapable adults",
            "8.5.1(d)",
            "C3",
            120,
            70,
            "C3",
        ),
        Occupancy(
            "penalChildren",
            "Penal and mental institution, children",
            "8.5.1(d)",
            "C4",
            100,
            60,
            "C4",
        ),
        Occupancy(
            "penalAdults", "Penal and mental institution, adults", "8.5.1(d)", "C5", 120, 70, "C5"
        ),
        Occupancy(
            "hospital", "Normal medical facility (small hospital)", "8.5.1(d)", "D1", 340, 225, "D1"
        ),
        Occupancy(
            "hospitalLarge", "Big hospital (over 100 beds)", "8.5.1(d)", "D1", 450, 250, "D1"
        ),
        Occupancy(
            "emergencyMedical", "Emergency medical facility", "8.5.1(d)", "D2", 300, 135, "D2"
        ),
        Occupancy(
            "nursesQuarters", "Nurses and medical quarters", "8.5.1(d)", "D2", 250, 135, "D2"
        ),
        Occupancy("office", "Office", "8.5.1(d)", "E1", 45, 30, "E1"),
        Occupancy("laboratory", "Research and testing laboratory", "8.5.1(d)", "E2", 70, 45, "E2"),
        Occupancy("essentialServices", "Essential services", "8.5.1(d)", "E3", 70, 45, "E3"),
        Occupancy("shop", "Small shops and market", "8.5.1(d)", "F1", 45, 30, "F1"),
        Occupancy("largeShop", "Large shops and market", "8.5.1(d)", "F2", 45, 30, "F2"),
        Occupancy("refueling", "Refueling station", "8.5.1(d)", "F3", 70, 45, "F3"),
        Occupancy("industryLow", "Low hazard industry", "8.5.1(d)", "G1", 40, 25, "G1"),
        Occupancy("industryModerate", "Moderate hazard industry", "8.5.1(d)", "G2", 40, 25, "G2"),
        Occupancy("storageLow", "Low fire risk storage", "8.5.1(d)", "H1", 10, 6, "H1"),
        Occupancy("storageModerate", "Moderate fire risk storage", "8.5.1(d)", "H2", 10, 6, "H2"),
        Occupancy(
            "assemblyLargeFixed",
            "Large assembly with fixed seats (per seat)",
            "8.5.1(d)",
            "I1",
            90,
            45,
            "I1",
            "seat",
        ),
        Occupancy(
            "assemblySmallFixed",
            "Small assembly with fixed seats (per seat)",
            "8.5.1(d)",
            "I2",
            90,
            45,
            "I2",
            "seat",
        ),
        Occupancy(
            "assemblyLarge", "Large assembly without fixed seats", "8.5.1(d)", "I3", 15, 10, "I3"
        ),
        Occupancy(
            "assemblySmall", "Small assembly without fixed seats", "8.5.1(d)", "I4", 15, 10, "I4"
        ),
        Occupancy("sports", "Sports facility", "8.5.1(d)", "I5", 15, 10, "I5"),
        Occupancy("hazardExplosion", "Explosion hazard building", "8.5.1(d)", "J1", 15, 10, "J1"),
        Occupancy("hazardChemical", "Chemical hazard building", "8.5.1(d)", "J2", 15, 10, "J2"),
        Occupancy("hazardBiological", "Biological hazard building", "8.5.1(d)", "J3", 10, 6, "J3"),
        Occupancy("hazardRadiation", "Radiation hazard building", "8.5.1(d)", "J4", 10, 6, "J4"),
        Occupancy("parking", "Parking garage (visitors)", "8.5.1(d)", "K1", 15, 10, "K1"),
        Occupancy("privateGarage", "Private garage (visitors)", "8.5.1(d)", "K2", 15, 10, "K2"),
        Occupancy("repairGarage", "Repair garage (visitors)", "8.5.1(d)", "K3", 15, 10, "K3"),
        Occupancy("utility", "Utility", "8.5.1(d)", "L", 10, 6, "L"),
        Occupancy("tanksTowers", "Fences, tanks and towers", "8.5.1(d)", "M2", None, 3, "M2"),
    )
}
OCCUPANCY_KEYS: tuple[str, ...] = tuple(OCCUPANCIES)

#: Sec 5.6.3: family size for residential units when the occupants are not known.
FAMILY_SIZE = 5
#: Sec 5.6.4: office floor space per person, 7.4 to 9.3 m²; the smaller (more people).
OFFICE_AREA_PER_PERSON = 7.4

# ─────────────────────────── Sec 5.9 storage and 5.10 distribution ───────────────────────────

#: Sec 5.9.1.2(c): roof tank = 1/2 daily demand, underground reservoir = 1 x daily demand, each
#: plus a 1 hour fire-fighting reserve for a tall building.
ROOF_TANK_FRACTION = 0.5
RESERVOIR_FRACTION = 1.0
FIRE_RESERVE_HOURS = 1.0

#: Eq 8.5.1: peak hourly demand = daily requirement / hours of consumption (usually 15 to 17)
#: x peak factor (usually 2.2).
CONSUMPTION_HOURS = 16.0
PEAK_FACTOR = 2.2

#: Table 8.5.2: storage tank drain pipe diameter by tank capacity (upper bound litres, mm).
TANK_DRAIN = [(2800, 25), (5500, 38), (11000, 50), (19000, 63), (28000, 75), (None, 100)]
#: Table 8.5.3: overflow pipe diameter by the inflow (upper bound l/min, mm).
TANK_OVERFLOW = [
    (190, 50),
    (570, 63),
    (760, 75),
    (1500, 100),
    (2650, 125),
    (3800, 150),
    (None, 200),
]

#: Sec 5.10.1(c)(ii): "probable maximum velocity of flow against tentative diameter of pipes":
#: 13 and 50 mm: 0.30 - 0.60 m/s, 75 and 100 mm: 0.75 - 0.90 m/s, 150 and 200 mm: 1.15 - 1.30
#: m/s. SAEngine reads each pair of diameters with the pair of velocities in the same order
#: (13 mm 0.30, 50 mm 0.60, ...) and interpolates linearly between them.
VELOCITY_LIMITS = [(13, 0.30), (50, 0.60), (75, 0.75), (100, 0.90), (150, 1.15), (200, 1.30)]
#: Sec 5.10.1(c)(ii): maximum permissible head loss 1.5-1.6 m per 100 m; the upper value.
MAX_HEAD_LOSS = 1.6  # m per 100 m

#: Diameters of supply pipes as BNBC's Part 8 tables name them (Tables 8.5.2, 8.5.6, 8.O.2).
SUPPLY_DIAMETERS = [13, 19, 25, 32, 38, 50, 63, 75, 100, 125, 150, 200]

#: Table 8.5.6: required flow pressure at the fixture [kPa]: 55 for flush tanks and faucets,
#: 100 for flushometer valves (water closet, pedestal urinal).
FLOW_PRESSURE_TANK = 55.0
FLOW_PRESSURE_VALVE = 100.0
#: Sec 5.10.4.2: no fitting subject to a head greater than 35 m (345 kPa); Sec 5.11.1: tall
#: buildings, not greater than 350 kPa, zoned by intermediate tanks every 5 - 6 storeys.
MAX_STATIC_HEAD = 35.0  # m
#: Part 3 Sec 2.4.4: high-rise when a floor for human occupancy is more than 33 m above ground.
HIGH_RISE = 33000.0  # mm

#: Table 8.5.5: probable simultaneous demand: (fixture units, flush tank flow, flush valve
#: flow) in l/min.
HUNTER = [
    (20, 56.6, 133.1),
    (40, 93.4, 178.4),
    (60, 121.8, 209.5),
    (80, 144.4, 235.0),
    (100, 161.4, 257.7),
    (120, 181.2, 277.5),
    (140, 201.0, 294.5),
    (160, 215.2, 311.5),
    (180, 232.2, 328.5),
    (200, 243.5, 348.3),
    (220, 260.5, 359.6),
    (240, 271.8, 370.9),
    (300, 322.8, 416.2),
    (400, 396.4, 481.4),
    (500, 472.9, 538.0),
    (600, 549.3, 597.5),
    (700, 606.0, 651.3),
    (800, 682.4, 693.7),
    (900, 739.0, 739.0),
    (1000, 795.7, 795.7),
]


@dataclass(frozen=True)
class SupplyUnits:
    """Water supply fixture units of a fixture: cold, hot and total, and where they come from."""

    cold: float
    hot: float
    total: float
    source: str
    minimum: int  # minimum supply pipe [mm], Table 8.5.6 (or Table 8.5.4's branch)


#: Supply fixture units per fixture. Appendix O (Sec O.3) computes the demand in water supply
#: fixture units of Table 8.O.1, the scale of Table 8.5.5 (Hunter). Fixtures Table 8.O.1 does
#: not list take Table 8.5.4's units, split 75 % cold / 75 % hot as the note of Table 8.O.1
#: says for fixtures with both supplies. Minimum supply pipe from Table 8.5.6.
SUPPLY_UNITS: dict[str, SupplyUnits] = {
    "wc": SupplyUnits(5, 0, 5, "Table 8.O.1 water closet, flush tank", 19),
    "wcValve": SupplyUnits(10, 0, 10, "Table 8.O.1 water closet, flush valve", 25),
    "urinal": SupplyUnits(3, 0, 3, "Table 8.O.1 stall or wall urinal, flush tank", 13),
    "urinalValve": SupplyUnits(5, 0, 5, "Table 8.O.1 stall or wall urinal, flush valve", 19),
    "basin": SupplyUnits(0.75, 0.75, 1, "Table 8.5.4 wash basin (domestic use)", 19),
    "shower": SupplyUnits(3, 3, 4, "Table 8.O.1 shower head, mixing valve", 13),
    "bathtub": SupplyUnits(1.5, 1.5, 2, "Table 8.O.1 bathtub, faucet", 13),
    "kitchenSink": SupplyUnits(1.5, 1.5, 2, "Table 8.O.1 kitchen sink, faucet", 13),
    "washingMachine": SupplyUnits(2.25, 2.25, 3, "Table 8.5.4 washing machine", 13),
    "bidet": SupplyUnits(1.5, 1.5, 2, "Table 8.O.1 bidet, faucet", 13),
    "floorDrain": SupplyUnits(0, 0, 0, "no supply", 0),
}

# ───────────────────────────────── Chapter 6: drainage ─────────────────────────────────


@dataclass(frozen=True)
class DrainageUnits:
    units: float
    source: str
    outlet: int  # minimum internal diameter of the waste outlet [mm], Table 8.6.2
    soil: bool  # a soil appliance (Table 8.6.2): goes to a soil (or soil-and-waste) stack


#: Table 8.6.12 fixture units, Table 8.6.2 minimum outlets. The washing machine is not in
#: Table 8.6.12: Table 8.6.13 by its trap, taken (SAEngine) as 50 mm, 3 units.
DRAINAGE_UNITS: dict[str, DrainageUnits] = {
    "wc": DrainageUnits(3, "Table 8.6.12 water closet, tank operated", 100, True),
    "wcValve": DrainageUnits(6, "Table 8.6.12 water closet, valve operated", 100, True),
    "urinal": DrainageUnits(4, "Table 8.6.12 urinal, wall hung", 40, True),
    "basin": DrainageUnits(1, "Table 8.6.12 wash basin, ordinary", 32, False),
    "shower": DrainageUnits(2, "Table 8.6.12 shower stall, domestic", 40, False),
    "bathtub": DrainageUnits(2, "Table 8.6.12 bathtub", 50, False),
    "kitchenSink": DrainageUnits(2, "Table 8.6.12 kitchen sink, domestic", 40, False),
    "floorDrain": DrainageUnits(1, "Table 8.6.12 floor trap", 65, False),
    "washingMachine": DrainageUnits(3, "Table 8.6.13, 50 mm trap (SAEngine)", 50, False),
    "bidet": DrainageUnits(2, "Table 8.6.12 bidet", 32, False),
}

#: Table 8.6.13: fixture units of a fixture from its drain or trap size (mm, units).
TRAP_UNITS = [(30, 1), (40, 2), (50, 3), (65, 4), (75, 5), (100, 6)]

#: Table 8.6.14: (diameter, any horizontal fixture branch, one stack of 3 storeys or 3
#: intervals, more than 3 storeys: total for stack, total at one storey or branch interval).
#: None where the table says "sizing load based on design criteria".
STACKS = [
    (30, 1, 2, 2, 1),
    (40, 3, 4, 8, 2),
    (50, 6, 10, 24, 6),
    (65, 12, 20, 42, 9),
    (75, 20, 30, 60, 16),
    (100, 160, 240, 500, 90),
    (125, 360, 540, 1100, 200),
    (150, 620, 960, 1900, 350),
    (200, 1400, 2200, 3600, 600),
    (250, 2500, 3800, 5600, 1000),
    (300, 3900, 6000, 8400, 1500),
    (375, 7000, None, None, None),
]

#: Table 8.6.15: building drain or sewer, fixture units by slope; None where the table has "-".
DRAIN_SLOPES = [1 / 200, 1 / 100, 1 / 50, 1 / 25]
BUILDING_DRAINS = [
    (100, (None, 180, 216, 250)),
    (150, (None, 700, 840, 1000)),
    (200, (1400, 1600, 1920, 2300)),
    (250, (2500, 2900, 3500, 4200)),
    (300, (2900, 4600, 5600, 6700)),
    (375, (7000, 8300, 10000, 12000)),
]

#: Table 8.6.16: (stack diameter, fixture units, {vent diameter: maximum developed length m}).
VENT_STACKS = [
    (30, 2, {30: 9}),
    (40, 8, {30: 15, 40: 45.5}),
    (40, 10, {30: 9, 40: 30.5}),
    (50, 12, {30: 9, 40: 22.5, 50: 61}),
    (50, 20, {30: 8, 40: 15, 50: 45.5}),
    (65, 42, {40: 9, 50: 30.5, 65: 91.5}),
    (75, 10, {40: 12.5, 50: 45.5, 65: 109.5, 75: 317}),
    (75, 21, {40: 9.5, 50: 33.5, 65: 82, 75: 247}),
    (75, 53, {40: 8, 50: 28.5, 65: 70, 75: 207}),
    (75, 102, {40: 7.5, 50: 26, 65: 64, 75: 189}),
    (100, 43, {50: 10.5, 65: 26, 75: 76, 100: 298.5}),
    (100, 140, {50: 8, 65: 19.5, 75: 61, 100: 228.5}),
    (100, 320, {50: 7, 65: 16.5, 75: 52, 100: 195}),
    (100, 540, {50: 6.5, 65: 15, 75: 45.5, 100: 176.5}),
    (125, 190, {65: 8.5, 75: 25, 100: 97.5, 125: 301.5}),
    (125, 490, {65: 6.5, 75: 19, 100: 76, 125: 231.5}),
    (125, 940, {65: 5.5, 75: 16, 100: 64, 125: 204}),
    (125, 1400, {65: 4.5, 75: 15, 100: 58, 125: 180}),
    (150, 500, {75: 10, 100: 39.5, 125: 122, 150: 305}),
    (150, 1100, {75: 6.5, 100: 30.5, 125: 94.5, 150: 237.5}),
    (150, 2000, {75: 6, 100: 25.5, 125: 79, 150: 201}),
    (150, 2900, {100: 23.5, 125: 73, 150: 183}),
    (200, 1800, {100: 9.5, 125: 29, 150: 73, 200: 286.5}),
    (200, 3400, {100: 7, 125: 22, 150: 58, 200: 219.5}),
    (200, 5600, {100: 6, 125: 19, 150: 48.5, 200: 186}),
    (200, 7600, {100: 5.5, 125: 17, 150: 42.5, 200: 170.5}),
    (250, 4000, {125: 9.5, 150: 23.5, 200: 94.5, 250: 292.5}),
    (250, 7200, {125: 7, 150: 18, 200: 73, 250: 225.5}),
    (250, 11000, {125: 6, 150: 15.5, 200: 61, 250: 192}),
    (250, 15000, {125: 5.5, 150: 14, 200: 55, 250: 173.5}),
    (300, 7300, {150: 9.5, 200: 36.5, 250: 116, 300: 286.5}),
    (300, 13000, {150: 7, 200: 28.5, 250: 91.5, 300: 219.5}),
    (300, 20000, {150: 6, 200: 24, 250: 76, 300: 186}),
    (300, 26000, {150: 5.5, 200: 22, 250: 70, 300: 152.5}),
    (375, 15000, {200: 12, 250: 39.5, 300: 94.5}),
    (375, 25000, {200: 9.5, 250: 29, 300: 73}),
    (375, 38000, {200: 8, 250: 24.5, 300: 61}),
    (375, 50000, {200: 7, 250: 22.5, 300: 55}),
]

NL = float("inf")  # "NL": no limit
#: Table 8.6.17: (branch diameter, slope mm/m, {vent diameter: maximum developed length m}); a
#: "-" entry (not permitted) is left out.
BRANCH_VENTS = [
    (30, 20, {30: NL}),
    (30, 40, {30: NL}),
    (40, 20, {30: NL, 40: NL}),
    (40, 40, {30: NL, 40: NL}),
    (50, 10, {30: NL, 40: NL, 50: NL}),
    (50, 20, {30: 88, 40: NL, 50: NL}),
    (50, 40, {30: 45, 40: 115, 50: NL}),
    (65, 10, {30: 54, 40: 137, 50: NL}),
    (65, 20, {30: 29, 40: 73, 50: NL, 65: NL}),
    (65, 40, {30: 15, 40: 39, 50: NL, 65: NL}),
    (75, 10, {40: 58, 50: NL, 65: NL, 75: NL}),
    (75, 20, {40: 29.5, 50: 128, 65: NL, 75: NL}),
    (75, 40, {40: 15, 50: 67, 65: NL, 75: NL}),
    (100, 10, {50: 58, 65: NL, 75: NL, 100: NL}),
    (100, 20, {50: 30, 65: 94, 75: NL, 100: NL}),
    (100, 40, {50: 14.5, 65: 48.5, 75: 125, 100: NL}),
    (125, 10, {75: 149, 100: NL, 125: NL}),
    (125, 20, {65: 58, 75: 76, 100: NL, 125: NL}),
    (125, 40, {65: 29.5, 75: 39.5, 100: NL, 125: NL}),
    (150, 10, {100: NL, 125: NL, 150: NL}),
    (150, 20, {65: 14, 75: 58, 100: 76, 125: NL, 150: NL}),
    (150, 40, {75: 29.5, 100: 39.5, 125: NL, 150: NL}),
    (200, 10, {125: NL, 150: NL, 200: NL}),
    (200, 20, {75: 14, 100: 58, 125: 94.5, 150: NL, 200: NL}),
    (200, 40, {100: 27.5, 125: 45.5, 150: 125, 200: NL, 250: NL}),
]

#: Sec 6.10.2.1: building drains half full, self-cleansing 0.75 m/s (not below 0.6), at most
#: 2.5 m/s.
DRAIN_VELOCITY = (0.6, 0.75, 2.5)

# ──────────────────────────────── septic tank (Sec 6.9.12) ────────────────────────────────

SEPTIC_MIN_VOLUME = 2000.0  # l, Sec 6.9.12.8
SEPTIC_MIN_WIDTH = 1000.0  # mm, Sec 6.9.12.8
SEPTIC_MIN_DEPTH = 1000.0  # mm liquid depth, Sec 6.9.12.8
SEPTIC_LENGTH_RATIO = (3.0, 4.0)  # length at least 3, recommended at most 4 widths
SEPTIC_MAX_USERS = 300  # residential, Sec 6.9.12.9 (Imhoff tank above, Sec 6.9.13.2)
SEPTIC_SLUDGE = 40.0  # l/capita/year (0.04 m³), Sec 6.9.12.10
SEPTIC_CLEARANCE = 300.0  # mm, liquid level to the cover slab, Sec 6.9.12.10
SEPTIC_RETENTION = 1.0  # day, minimum, Sec 6.9.12.11
SEPTIC_DESLUDGING = 1.0  # year: Appendix S "minimum 1 year"; Sec 6.9.12.12 6 months to 1 year
SEPTIC_TWO_CHAMBERS = 3000.0  # l: two chambers recommended above, Sec 6.9.12.13
SEPTIC_INLET_FRACTION = 2 / 3  # inlet compartment, Sec 6.9.12.13
SEPTIC_COVER_LIVE = 7.0  # kPa, cover and roof design live load, Sec 6.9.12.14
#: Appendix S: waste water flow in the absence of data: occupancy groups A, C and D 120 lpcd
#: for cities (50 district town, 20 thana and rural); other groups 10 lpcd.
SEPTIC_FLOW_CITY = 120.0
SEPTIC_FLOW_OTHER = 10.0
#: Table 8.S.1 reduction factors (applied to the persons served) for the occupancies of
#: Table 8.5.1 that it covers.
SEPTIC_REDUCTION: dict[str, tuple[float, str]] = {
    "school": (0.25, "Table 8.S.1 (ii) primary and secondary school"),
    "college": (0.25, "Table 8.S.1 (iii) institution of higher learning"),
    "preschool": (0.08, "Table 8.S.1 (iv) kindergarten"),
    "office": (0.50, "Table 8.S.1 (xi) office, no. of staff"),
    "hotel": (0.70, "Table 8.S.1 (x) hotel, no. of beds"),
    "shop": (0.25, "Table 8.S.1 (vi) market, hawker/employee"),
    "largeShop": (0.25, "Table 8.S.1 (vi) market, hawker/employee"),
    "industryLow": (0.50, "Table 8.S.1 (v) factory, one shift per 24 hours"),
    "industryModerate": (0.50, "Table 8.S.1 (v) factory, one shift per 24 hours"),
    "assemblyLargeFixed": (0.03, "Table 8.S.1 (viii) cinema, hall seating capacity"),
    "assemblySmallFixed": (0.03, "Table 8.S.1 (viii) cinema, hall seating capacity"),
}

#: Table 8.6.8: minimum distance [m] from (component) to (other): building foundation, well,
#: stream, seepage pit, dry well; None where the table has "-".
DISPOSAL_DISTANCES = {
    "septic": {"building": 1.5, "well": 8, "stream": None, "seepagePit": 1.5, "dryWell": None},
    "disposalField": {"building": 3, "well": 15, "stream": 7.5, "seepagePit": 6, "dryWell": 6},
    "seepagePit": {"building": 4.5, "well": 15, "stream": 15, "seepagePit": 6, "dryWell": 6},
    "dryWell": {"building": 3, "well": 15, "stream": None, "seepagePit": 6, "dryWell": None},
}
#: Table 8.6.9: minimum horizontal separation [m] of treatment tanks (septic, Imhoff).
TREATMENT_TANK_DISTANCES = {
    "building": 1.5,
    "cistern": 7.5,
    "foundationWall": 1.5,
    "lake": 7.5,
    "lotLine": 0.6,
    "pond": 7.5,
    "reservoir": 7.5,
    "spring": 15,
    "stream": 7.5,
    "swimmingPool": 4.5,
    "waterService": 1.5,
    "well": 7.5,
}

#: Table 8.6.10: percolation rate (minutes for water to fall 25 mm, upper bound) -> effluent
#: allowance [l/m²/day] of a disposal field trench bottom and of a seepage pit's wall area.
#: Above 60 minutes the soil is not suitable.
ABSORPTION = [(2, 128, 172), (5, 96, 128), (10, 68, 92), (30, 32, 44), (60, 16, 24)]
#: Sec 6.9.15.3: seepage units hold at least twice the septic tank's liquid volume; Sec
#: 6.9.15.4: the bottom at least 1 m above the highest water table.
SEEPAGE_CAPACITY_FACTOR = 2.0
SEEPAGE_ABOVE_WATER_TABLE = 1000.0  # mm

#: SAEngine: a first estimate of the percolation rate [min/25 mm] from the soil type of the
#: top layers of 01 Soil Report, until the percolation tests Sec 6.9.15.2 requires (at least
#: three holes) are done. Typical ranges for these soils, not BNBC values.
PERCOLATION_BY_SOIL = {
    "gravel": 2.0,
    "sand": 5.0,
    "siltySand": 10.0,
    "silt": 30.0,
    "clay": 60.0,
    "organic": 120.0,
    "rock": 120.0,
}

# ──────────────────────────────── Chapter 7: rainwater ────────────────────────────────

#: Tables 8.7.2-8.7.4 are for 25 mm/h; the areas scale with 25 / intensity (their notes and
#: Appendix U).
TABLE_RAINFALL = 25.0
#: Appendix R Figure 8.R.1 (one-hour rainfall, 25-year return period): Dhaka lies between the
#: 85 mm and 90 mm isohyets; interpolated (Appendix R (c)), about 88 mm. User editable.
DHAKA_RAINFALL = 88.0
#: Sec 7.4.1: plots of 300 m² or more harvest rainwater.
HARVEST_PLOT = 300.0
#: Sec 7.8.9: days of storage: 90 for drinking, cooking, bathing and ablution, 210 for other uses.
HARVEST_DAYS = {"potable": 90, "other": 210}
#: Table 8.7.2: (leader diameter, maximum projected roof area m², flow l/min).
LEADERS = [
    (50, 202, 87),
    (65, 367, 155),
    (75, 598, 253),
    (100, 1287, 544),
    (125, 2336, 986),
    (150, 3790, 1602),
    (200, 8180, 3450),
]
#: Table 8.7.3: semicircular gutters: diameter -> {slope mm/m: (area m², flow l/min)}.
GUTTERS = [
    (75, {5: (61, 25), 10: (87, 36), 20: (123, 51), 40: (174, 73)}),
    (100, {5: (130, 55), 10: (185, 77), 20: (260, 110), 40: (370, 155)}),
    (125, {5: (227, 96), 10: (320, 136), 20: (455, 192), 40: (645, 273)}),
    (150, {5: (350, 148), 10: (495, 210), 20: (700, 296), 40: (1010, 425)}),
    (175, {5: (503, 210), 10: (710, 300), 20: (1000, 425), 40: (1420, 600)}),
    (200, {5: (725, 307), 10: (1020, 430), 20: (1300, 610), 40: (2040, 862)}),
    (250, {5: (1300, 555), 10: (1850, 785), 20: (2610, 1110), 40: (3650, 1540)}),
]
#: Table 8.7.4: horizontal storm drains: diameter -> {slope mm/m: (area m², flow l/min)}.
STORM_DRAINS = [
    (75, {10: (299, 125), 20: (422, 177), 40: (599, 252)}),
    (100, {10: (668, 288), 20: (965, 406), 40: (1370, 577)}),
    (125, {10: (1215, 515), 20: (1715, 725), 40: (2430, 1030)}),
    (150, {10: (1950, 823), 20: (2745, 1157), 40: (3900, 1645)}),
    (200, {10: (4185, 1765), 20: (5940, 2500), 40: (8380, 3540)}),
    (250, {10: (7550, 3185), 20: (10650, 4500), 40: (15100, 6370)}),
    (300, {10: (12140, 5100), 20: (17140, 7236), 40: (24280, 10250)}),
    (375, {10: (21700, 9120), 20: (30600, 12900), 40: (43400, 18300)}),
]
#: Sec 7.10.6.3: subsurface rainwater drainage piping not less than 100 mm.
MIN_STORM_DRAIN = 100

# ────────────────────────── Part 4 Table 4.4.1: fire protection flows ──────────────────────────

#: Table 4.4.1: (sprinkler, standpipe and hose) l/min by hazard; durations by height.
FIRE_FLOWS = {
    "lightI": (1000, 1000),
    "lightII": (1900, 1900),
    "ordinaryI": (2650, 1900),
    "ordinaryII": (3200, 1900),
    "ordinaryIII": (4800, 1900),
}
#: Table 4.4.1 note **: "Values will be for one riser serving floor area of 1000 m2" [m²].
FIRE_RISER_AREA = 1000.0
#: Notes of Table 4.4.1: hazard class of the Part 3 occupancy groups (a group letter alone
#: covers all its subgroups). Group J: extra hazard, at least ordinary hazard-III.
FIRE_HAZARD = {
    "A1": "lightI",
    "A2": "lightI",
    "A3": "lightI",
    "E1": "lightI",
    "A4": "lightII",
    "A5": "lightII",
    "B": "lightII",
    "C": "lightII",
    "D": "lightII",
    "E2": "lightII",
    "E3": "lightII",
    "I2": "lightII",
    "I4": "lightII",
    "F1": "lightII",
    "I1": "ordinaryI",
    "I3": "ordinaryI",
    "I5": "ordinaryI",
    "F2": "ordinaryI",
    "F3": "ordinaryI",
    "G1": "ordinaryI",
    "G2": "ordinaryII",
    "H1": "ordinaryII",
    "H2": "ordinaryIII",
    "J": "ordinaryIII",
}
HAZARD_ORDER = ["lightI", "lightII", "ordinaryI", "ordinaryII", "ordinaryIII"]


def fire_hazard(group: str) -> str | None:
    """Table 4.4.1's hazard class of a Part 3 occupancy group, or None when it lists none."""
    return FIRE_HAZARD.get(group) or FIRE_HAZARD.get(group[:1])


# ─────────────────────── SAEngine: pipe outside diameters, friction ───────────────────────

#: SAEngine (from memory, to be checked against the manufacturer): outside diameter [mm] of a
#: pipe of a nominal size: plastics (uPVC, PPR, HDPE) by the ISO metric series, metal (GI, CI)
#: by ISO 65 / BS EN 10255. The nominal size is BNBC's (13 = 1/2 in, 19 = 3/4 in, ...).
OUTSIDE_DIAMETER = {
    "plastic": {
        13: 20,
        19: 25,
        25: 32,
        30: 40,
        32: 40,
        38: 50,
        40: 50,
        50: 63,
        63: 75,
        65: 75,
        75: 90,
        100: 110,
        125: 140,
        150: 160,
        175: 200,
        200: 225,
        250: 280,
        300: 315,
        375: 400,
    },
    "metal": {
        13: 21.3,
        19: 26.9,
        25: 33.7,
        30: 42.4,
        32: 42.4,
        38: 48.3,
        40: 48.3,
        50: 60.3,
        63: 76.1,
        65: 76.1,
        75: 88.9,
        100: 114.3,
        125: 139.7,
        150: 165.1,
        175: 193.7,
        200: 219.1,
        250: 273.0,
        300: 323.9,
        375: 406.4,
    },
}
#: SAEngine (from memory, to be checked): Hazen-Williams C of the pipe materials.
HAZEN_C = {"uPVC": 150, "PPR": 150, "HDPE": 150, "GI": 120, "CI": 100}
#: SAEngine practice (BNBC Part 8 gives no sleeve rule): a sleeve's inside diameter is the
#: pipe's outside diameter plus 50 mm (25 mm all round for movement and fire stopping),
#: rounded up to a standard sleeve size.
SLEEVE_CLEARANCE = 50.0
SLEEVE_SIZES = [50, 65, 80, 100, 125, 150, 200, 250, 300, 350, 400, 450, 500]
#: SAEngine practice: the clear plan area a pipe takes in a shaft, a square of its outside
#: diameter plus 100 mm (50 mm all round for fixing and insulation).
SHAFT_CLEARANCE = 100.0

"""BNBC 2020 Part 4 (fire protection) as data, and the few NFPA values the code leaves out.

Every BNBC value is transcribed from the rendered page of the Bangladesh Gazette edition of
11 February 2021 (``bnbc-2020-part1.pdf`` holds Parts 1 to 6); ``PAGES`` gives the PDF page of
each table and clause. BNBC 2020 Part 4 Chapter 4 gives the flows, durations, pressures, pump
ratings, pipe schedules and sprinkler spacing; Chapter 5 says which systems each occupancy needs.
It leaves the sprinkler design density, the hose allowance, the jockey pump and the extinguisher
ratings to NFPA (NFPA 10, 13, 20): those values are SAEngine's recollection of NFPA, each marked
``MEMORY`` ("from memory, to be checked") wherever it is reported. Values marked "SAEngine" are
documented assumptions where both are silent.

Units: l/min, kPa, m, m², mm as the tables give them.
"""

from __future__ import annotations

from saengine.plumbing.tables import FIRE_FLOWS, FIRE_HAZARD, FIRE_RISER_AREA, HAZARD_ORDER

#: Where each table or clause is (PDF page of the Gazette edition).
PAGES: dict[str, str] = {
    "high-rise": "BNBC 2020 Part 1 Chapter 2 definitions and Part 3 Sec 2.4.4 (p6) and p94",
    "4:2.1": "BNBC 2020 Part 4 Sec 2.1 (p285)",
    "4:2.12.9": "BNBC 2020 Part 4 Sec 2.12.9(iv) (p296)",
    "4.1.4": "BNBC 2020 Part 4 Sec 4.1.4 (p321)",
    "4.4.1": "BNBC 2020 Part 4 Table 4.4.1 (Sec 4.2.1) (p322)",
    "4.2.2.2": "BNBC 2020 Part 4 Sec 4.2.2.2(a)-(b) (p324)",
    "4.2.2.3": "BNBC 2020 Part 4 Sec 4.2.2.3 (p325)",
    "4.2.2.5": "BNBC 2020 Part 4 Sec 4.2.2.5 (p325-326)",
    "4.2.3.2": "BNBC 2020 Part 4 Sec 4.2.3.2 (p326-327)",
    "4.2.3.3": "BNBC 2020 Part 4 Sec 4.2.3.3 (p327)",
    "4.2.3.4": "BNBC 2020 Part 4 Sec 4.2.3.4 (p328)",
    "4.4.2": "BNBC 2020 Part 4 Table 4.4.2 (p328)",
    "4.2.3.5": "BNBC 2020 Part 4 Sec 4.2.3.5 (p328)",
    "4.2.3.7": "BNBC 2020 Part 4 Sec 4.2.3.7 (p328)",
    "4.2.3.8": "BNBC 2020 Part 4 Sec 4.2.3.8 (p329)",
    "4.2.3.10": "BNBC 2020 Part 4 Sec 4.2.3.10-4.2.3.11 (p329)",
    "4.2.3.13": "BNBC 2020 Part 4 Sec 4.2.3.13 (p330)",
    "4.2.3.14": "BNBC 2020 Part 4 Sec 4.2.3.14 (p330)",
    "4.2.3.15": "BNBC 2020 Part 4 Sec 4.2.3.15 (p330)",
    "4.2.4": "BNBC 2020 Part 4 Sec 4.2.4 (p330)",
    "4.2.10.6": "BNBC 2020 Part 4 Sec 4.2.10.6 (p332)",
    "4.2.11": "BNBC 2020 Part 4 Sec 4.2.11.1-4.2.11.2 (p332)",
    "4.4.5": "BNBC 2020 Part 4 Table 4.4.5 (p332-333)",
    "4.4.6": "BNBC 2020 Part 4 Table 4.4.6 (p333)",
    "4.4.7": "BNBC 2020 Part 4 Table 4.4.7 (p333-334)",
    "4.2.12.2": "BNBC 2020 Part 4 Sec 4.2.12.2 (p334)",
    "4.4.2.ext": "BNBC 2020 Part 4 Sec 4.4.2 (p337)",
    "4.5": "BNBC 2020 Part 4 Sec 4.5 (p338-339)",
    "4.6.2.2": "BNBC 2020 Part 4 Sec 4.6.2.2 (p341)",
    "5.1.6": "BNBC 2020 Part 4 Sec 5.1.6 (p346)",
    "5.2": "BNBC 2020 Part 4 Sec 5.2.1-5.2.5 (p347)",
    "5.3.1": "BNBC 2020 Part 4 Sec 5.3.1 (p347)",
    "5.3.2": "BNBC 2020 Part 4 Sec 5.3.2 (p348)",
    "5.3.3": "BNBC 2020 Part 4 Sec 5.3.3 (p348)",
    "5.3.4": "BNBC 2020 Part 4 Sec 5.3.4 (p348)",
    "5.4": "BNBC 2020 Part 4 Sec 5.4 (p349)",
    "5.5": "BNBC 2020 Part 4 Sec 5.5 (p349)",
    "5.6": "BNBC 2020 Part 4 Sec 5.6.1 (p349-350)",
    "5.7": "BNBC 2020 Part 4 Sec 5.7 (p350-351)",
    "5.8.1": "BNBC 2020 Part 4 Sec 5.8.1 (p351)",
    "5.8.2": "BNBC 2020 Part 4 Sec 5.8.2 (p351)",
    "5.8.3": "BNBC 2020 Part 4 Sec 5.8.3 (p352)",
    "5.9.1": "BNBC 2020 Part 4 Sec 5.9.1 (p352)",
    "5.9.2": "BNBC 2020 Part 4 Sec 5.9.2(o)-(p) (p353)",
    "5.10": "BNBC 2020 Part 4 Sec 5.10 (p354)",
    "5.11": "BNBC 2020 Part 4 Sec 5.11 (p354)",
    "5.12": "BNBC 2020 Part 4 Sec 5.12 (p355)",
    "5.13": "BNBC 2020 Part 4 Sec 5.13 (p355)",
    "5.14": "BNBC 2020 Part 4 Sec 5.14-5.15 (p355)",
    "8:5.5.3": "BNBC 2020 Part 8 Sec 5.5.3 (p1038)",
    "6:2.3.5": "BNBC 2020 Part 6 Sec 2.3.5 (p533)",
}

MEMORY = "from memory, to be checked"


def cite(key: str, clause: str = "") -> str:
    """The source of ``key`` with a sub-clause appended to its section, e.g.
    cite('5.7', '(ii)') -> 'Part 4 Sec 5.7(ii) (p350-351)'."""
    source = PAGES[key]
    if not clause:
        return source
    i = source.find(",")
    return source[:i] + clause + source[i:] if i >= 0 else source + clause


# ─────────────────────────────── definitions (Part 1, Part 3) ───────────────────────────────

#: High-rise: more than 10 storeys or 33 m from the reference datum (Part 1 definitions, p6);
#: floors for human occupancy more than 33 m above ground (Part 3 Sec 2.4.4, p94).
HIGH_RISE_HEIGHT = 33.0  # m
HIGH_RISE_STOREYS = 10
#: Sec 4.5 (p338): a high-rise building above 80 m is a tall building (pressure zones).
TALL_HEIGHT = 80.0  # m

# ───────────────────────────── Table 4.4.1 (p322): flows, durations ─────────────────────────────

HAZARDS = [*HAZARD_ORDER, "extra"]
HAZARD_LABELS = {
    "lightI": "Light hazard-I",
    "lightII": "Light hazard-II",
    "ordinaryI": "Ordinary hazard-I",
    "ordinaryII": "Ordinary hazard-II",
    "ordinaryIII": "Ordinary hazard-III",
    "extra": "Extra hazard",
}
#: (sprinkler, standpipe and hose) l/min by hazard, one riser serving 1000 m² (note **). Extra
#: hazard (group J): set by the Fire Department, at least ordinary hazard-III.
FLOWS = {**FIRE_FLOWS, "extra": FIRE_FLOWS["ordinaryIII"]}
RISER_AREA = FIRE_RISER_AREA  # m²
#: Durations [min] for building heights up to 51 m, 51 to 102 m, above 102 m.
DURATION_HEIGHTS = (51.0, 102.0)
DURATIONS = {
    "lightI": (30, 38, 45),
    "lightII": (50, 62, 75),
    "ordinaryI": (75, 95, 112),
    "ordinaryII": (75, 95, 112),
    "ordinaryIII": (75, 95, 112),
    "extra": (75, 95, 112),
}


def hazard_of(group: str) -> str | None:
    """Table 4.4.1's hazard class of a Part 3 occupancy group (J: extra), None when unlisted."""
    if group.startswith("J"):
        return "extra"
    return FIRE_HAZARD.get(group) or FIRE_HAZARD.get(group[:1])


def duration(hazard: str, height: float) -> int:
    """Table 4.4.1 duration [min] of a hazard for a building ``height`` [m]."""
    column = 0 if height <= DURATION_HEIGHTS[0] else 1 if height <= DURATION_HEIGHTS[1] else 2
    return DURATIONS[hazard][column]


# ─────────────────────────── standpipes, Sec 4.2.3 (p326-p330) ───────────────────────────

#: Sec 4.2.3.2: each additional standpipe adds 1000 l/min to the supply, at most 8 of them.
ADDITIONAL_STANDPIPE_FLOW = 1000.0
MAX_ADDITIONAL_STANDPIPES = 8
#: Sec 4.2.3.3: minimum residual pressure at the hose outlet [kPa]: 50 mm or larger hose 300,
#: first-aid hose (38 mm) 200; at most 2434 anywhere; above 700 at a 40 mm outlet a pressure
#: reducing device. Sec 4.2.2.2(a): 600 kPa for a combined sprinkler and hose system fed by a
#: roof gravity tank, with the static heights 31 m, 20.5 m and 62 m.
HOSE_PRESSURE = {"large": 300.0, "small": 300.0, "firstAid": 200.0}
COMBINED_PRESSURE = 600.0
MAX_PRESSURE = 2434.0
PRV_PRESSURE = 700.0
GRAVITY_HEIGHT = {"large": 31.0, "small": 31.0, "firstAid": 20.5, "combined": 62.0}
#: Sec 4.2.3.11: hose connection, large stream at least 100 mm, small 63 or 50 mm, first aid
#: 38 mm; hose at most 30 m long. Sec 4.2.3.10: outlet at most 1.5 m above the floor.
HOSE_SIZE = {"large": 100, "small": 63, "firstAid": 38}
HOSE_LENGTH = 30.0  # m
OUTLET_HEIGHT = 1.5  # m
#: Sec 4.2.4: a wet riser is not less than 100 mm internal diameter.
WET_RISER_MIN = 100
#: Sec 4.2.3.13-4.2.3.14 and 4.2.10.6: supports carry the water-filled pipe + 110 kg; hangers
#: five times the water-filled pipe + 110 kg; horizontal standpipe hangers at most 5 m apart.
SUPPORT_EXTRA = 110.0  # kg
HANGER_FACTOR = 5.0
HANGER_SPACING = 5.0  # m
#: Sec 4.2.12.2: test pressures [kPa]: standpipes 1400 or 150 % of the working pressure, two
#: hours; sprinklers 1000, or 350 above a working pressure over 650.
TEST_STANDPIPE = 1400.0
TEST_SPRINKLER = 1000.0

# ──────────────────────────── fire pumps, Sec 4.2.2.5 and Table 4.4.2 ────────────────────────────

#: Sec 4.2.2.5: the pump rated at a net pressure of 272 kPa or more.
PUMP_MIN_NET = 272.0  # kPa
#: Table 4.4.2: pump rating [l/min] -> minimum discharge pipe [mm].
PUMP_RATINGS = (
    (946, 75),
    (1136, 100),
    (1514, 100),
    (1703, 125),
    (1892, 125),
    (2839, 150),
    (3785, 150),
    (4731, 200),
    (5677, 200),
)

# ─────────────────────────── sprinklers, Tables 4.4.5-4.4.7 (p332-p334) ───────────────────────────

#: Table 4.4.5 (steel pipe): nominal size [mm] -> heads (light, ordinary, extra hazard);
#: None: no limit. Note ***: one riser serves at most 4850 m² (light, ordinary) or 2325 m²
#: (extra).
STEEL_SCHEDULE = (
    (25, 2, 2, 1),
    (32, 3, 3, 2),
    (38, 5, 5, 5),
    (50, 10, 10, 8),
    (63, 30, 20, 15),
    (75, 60, 40, 27),
    (88, 100, 65, 40),
    (100, None, 100, 55),
    (125, None, 160, 90),
    (150, None, 275, 150),
    (200, None, 400, 225),
)
#: Table 4.4.6 (copper pipe), the same columns; 200 mm: "***".
COPPER_SCHEDULE = (
    (25, 2, 2, 1),
    (32, 3, 3, 2),
    (38, 5, 5, 5),
    (50, 12, 12, 8),
    (63, 40, 25, 20),
    (75, 65, 45, 30),
    (88, 115, 75, 45),
    (100, None, 115, 65),
    (125, None, 180, 100),
    (150, None, 300, 170),
)
RISER_FLOOR_AREA = {"light": 4850.0, "ordinary": 4850.0, "extra": 2325.0}
#: Table 4.4.7: protected area [m²] and maximum spacing [m] of a sprinkler by construction.
COVERAGE = {
    "beams": {"light": (18.6, 4.6), "ordinary": (12.1, 4.6), "extra": (9.3, 3.7)},
    "openJoists": {"light": (20.9, 4.6), "ordinary": (12.1, 4.6), "extra": (9.3, 3.7)},
    "other": {"light": (15.6, 4.6), "ordinary": (12.1, 4.6), "extra": (9.3, 3.7)},
}


def family(hazard: str) -> str:
    """Light, ordinary or extra: the columns of Tables 4.4.5-4.4.7."""
    return "light" if hazard.startswith("light") else "extra" if hazard == "extra" else "ordinary"


# ──────────────────────────── NFPA, from memory (to be checked) ────────────────────────────

#: NFPA 13 density/area curves, the usual design points (MEMORY): hazard -> (density
#: [mm/min = l/min/m²], design area [m²]).
DENSITY_AREA = {
    "lightI": (4.1, 139.0),
    "lightII": (4.1, 139.0),
    "ordinaryI": (6.1, 139.0),
    "ordinaryII": (8.1, 139.0),
    "ordinaryIII": (8.1, 139.0),
    "extra": (12.2, 232.0),
}
#: NFPA 13 inside + outside hose stream allowance [l/min] and duration [min] (MEMORY).
HOSE_ALLOWANCE = {"light": (379.0, 30), "ordinary": (946.0, 60), "extra": (1893.0, 90)}
#: Standard spray sprinkler, K 80 l/min/bar^0.5 (K5.6 gpm/psi^0.5) and its least pressure
#: 0.5 bar (7 psi) (MEMORY).
K_FACTOR = 80.0
MIN_HEAD_PRESSURE = 50.0  # kPa
#: NFPA 13: branch lines along the long side of the design area, 1.2 x sqrt(area) (MEMORY).
DESIGN_AREA_LENGTH = 1.2
#: NFPA 20: jockey pump flow about 1 % of the main pump's rating (at least 4 l/min here), its
#: pressure 70 kPa (10 psi) above the main pump's churn; fire pump motors not overloaded at
#: 150 % flow (MEMORY).
JOCKEY_SHARE = 0.01
JOCKEY_ABOVE = 70.0  # kPa
OVERLOAD_FLOW = 1.5
OVERLOAD_HEAD = 0.65
#: NFPA 10 Table 6.2.1.1 (MEMORY): area per unit of A rating [m²], the smallest rating, the
#: largest area per extinguisher and the travel distance.
EXTINGUISHER = {
    "light": {"perUnit": 279.0, "rating": 2, "max": 1045.0},
    "ordinary": {"perUnit": 139.0, "rating": 2, "max": 1045.0},
    "extra": {"perUnit": 93.0, "rating": 4, "max": 1045.0},
}
EXTINGUISHER_TRAVEL = 22.9  # m
#: Sec 4.4.2 (p337): below 279 m² of floor, at least one extinguisher of the minimum size.
EXTINGUISHER_SMALL_FLOOR = 279.0  # m²
#: Smoke detectors, about one per 80 m² of ceiling (NFPA 72 9.1 m spacing, MEMORY); manual call
#: points, one per 1000 m² of floor and at least one a floor (SAEngine; at each exit in practice).
DETECTOR_AREA = 80.0
CALL_POINT_AREA = 1000.0

# ─────────────────────────────── SAEngine: pipes and pumps ───────────────────────────────

#: Nominal size (BNBC's: 38 = 1 1/2 in, 63 = 2 1/2 in, 88 = 3 1/2 in) -> inside diameter [mm]
#: of schedule 40 steel pipe (MEMORY, ASME B36.10).
STEEL_BORE = {
    25: 26.6, 32: 35.1, 38: 40.9, 50: 52.5, 63: 62.7, 75: 77.9, 88: 90.1, 100: 102.3,
    125: 128.2, 150: 154.1, 200: 202.7, 250: 254.5, 300: 303.2,
}  # fmt: skip
#: Copper tube (type L) bores (MEMORY); larger sizes as steel.
COPPER_BORE = {25: 26.0, 32: 32.1, 38: 38.2, 50: 50.4, 63: 62.6, 75: 74.8, 88: 87.0, 100: 99.2}
#: Hazen-Williams C, wet systems (NFPA 13 Table 23.4.4.8.1, MEMORY): black steel 120,
#: galvanized 120, copper 150.
HAZEN_C = {"steel": 120.0, "GI": 120.0, "copper": 150.0}
#: Weight of the empty pipe [kg/m] of schedule 40 steel (MEMORY).
STEEL_MASS = {
    25: 2.5, 32: 3.4, 38: 4.1, 50: 5.4, 63: 8.6, 75: 11.3, 88: 13.6, 100: 16.1, 125: 21.8,
    150: 28.3, 200: 42.5, 250: 60.3, 300: 73.8,
}  # fmt: skip
#: SAEngine: the largest velocity a fire main is sized for [m/s] (practice; BNBC sizes by the
#: hydraulic calculation or the schedules).
MAX_VELOCITY = 5.0
#: SAEngine: pump efficiencies for the motor power (typical, the selected pump's curve rules).
PUMP_EFFICIENCY = 0.65
JOCKEY_EFFICIENCY = 0.40
#: IEC motor sizes [kW].
MOTOR_SIZES = (
    0.75, 1.1, 1.5, 2.2, 3.0, 4.0, 5.5, 7.5, 11.0, 15.0, 18.5, 22.0, 30.0, 37.0, 45.0, 55.0,
    75.0, 90.0, 110.0, 132.0, 160.0, 200.0, 250.0,
)  # fmt: skip
#: SAEngine practice: the clear space round each pump set in the pump room, the strip for the
#: controllers along one wall [m].
PUMP_CLEARANCE = 1.0
CONTROLLER_STRIP = 1.2
#: SAEngine: a fire pump set's discharge centreline above its floor [m].
PUMP_CENTRE = 0.5

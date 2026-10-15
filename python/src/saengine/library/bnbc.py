"""Reference data from BNBC 2020 (Bangladesh National Building Code), Part 6, Chapter 2 (Loads).

Each table names the clause or table it comes from. The values are the code's defaults for the
project settings; the engineer can override every one of them, and should check them against the
edition of the code that governs the project.

Units: kN/m² (kPa) for area loads, m/s for wind speeds.
"""

from __future__ import annotations

from typing import NamedTuple

EDITION = "BNBC 2020"


class Location(NamedTuple):
    name: str
    #: Seismic zone (Table 6.2.14 / Figure 6.2.24, seismic zoning map of Bangladesh).
    zone: int
    #: Basic wind speed, 3-second gust at 10 m, 50-year return period [m/s] (Table 6.2.8).
    wind_speed: float


#: Seismic zone coefficient Z by zone (Table 6.2.14).
ZONE_COEFFICIENT = {1: 0.12, 2: 0.20, 3: 0.28, 4: 0.36}

#: District towns and their seismic zone and basic wind speed (Tables 6.2.8 and 6.2.15).
LOCATIONS: dict[str, Location] = {
    "dhaka": Location("Dhaka", 2, 65.7),
    "chattogram": Location("Chattogram", 3, 80.0),
    "coxsbazar": Location("Cox's Bazar", 3, 80.0),
    "khulna": Location("Khulna", 1, 73.3),
    "rajshahi": Location("Rajshahi", 1, 72.1),
    "sylhet": Location("Sylhet", 4, 61.1),
    "barishal": Location("Barishal", 1, 78.7),
    "rangpur": Location("Rangpur", 3, 65.3),
    "mymensingh": Location("Mymensingh", 3, 67.4),
    "cumilla": Location("Cumilla", 2, 61.4),
}


class OccupancyCategory(NamedTuple):
    description: str
    #: Seismic importance factor I (Table 6.2.17).
    seismic_importance: float
    #: Wind importance factor I (Table 6.2.9).
    wind_importance: float


#: Occupancy categories of buildings (Table 6.1.1).
OCCUPANCY_CATEGORIES: dict[str, OccupancyCategory] = {
    "I": OccupancyCategory(
        "Low hazard to human life on failure (agricultural, minor storage)", 1.00, 0.87
    ),
    "II": OccupancyCategory("Standard occupancy (all buildings not in I, III or IV)", 1.00, 1.00),
    "III": OccupancyCategory(
        "Substantial hazard: assembly, schools, health care without surgery", 1.25, 1.15
    ),
    "IV": OccupancyCategory(
        "Essential facilities: hospitals, fire and police stations, shelters", 1.50, 1.15
    ),
}


class AreaUse(NamedTuple):
    name: str
    #: Minimum uniformly distributed live load [kN/m²] (Table 6.2.3).
    live: float


#: Minimum uniformly distributed live loads by use of the floor area (Table 6.2.3, selection).
AREA_USES: dict[str, AreaUse] = {
    "residential": AreaUse("Residential: rooms and private corridors", 2.0),
    "residentialPublic": AreaUse("Residential: public rooms and corridors", 4.8),
    "office": AreaUse("Office", 2.4),
    "officeLobby": AreaUse("Office: lobbies and first-floor corridors", 4.8),
    "corridorAbove": AreaUse("Corridors above the first floor", 3.8),
    "classroom": AreaUse("School: classrooms", 1.9),
    "hospitalWard": AreaUse("Hospital: patient rooms", 1.9),
    "operatingRoom": AreaUse("Hospital: operating rooms, laboratories", 2.9),
    "assemblyFixed": AreaUse("Assembly: fixed seats", 2.9),
    "assemblyMovable": AreaUse("Assembly: movable seats, lobbies", 4.8),
    "retailGround": AreaUse("Retail: first floor", 4.8),
    "retailUpper": AreaUse("Retail: upper floors", 3.6),
    "storageLight": AreaUse("Storage: light", 6.0),
    "storageHeavy": AreaUse("Storage: heavy", 12.0),
    "parking": AreaUse("Parking: passenger vehicles", 1.9),
    "stairs": AreaUse("Stairs and exits", 4.8),
    "roof": AreaUse("Roof: ordinary flat, pitched or curved", 1.0),
    "roofGarden": AreaUse("Roof: gardens and assembly use", 4.8),
}


class StructuralSystem(NamedTuple):
    name: str
    #: Response reduction factor R, overstrength factor Ω0 and deflection amplification Cd
    #: (Table 6.2.19).
    r: float
    omega: float
    cd: float


STRUCTURAL_SYSTEMS: dict[str, StructuralSystem] = {
    "rcSmf": StructuralSystem("RC special moment frame", 8.0, 3.0, 5.5),
    "rcImf": StructuralSystem("RC intermediate moment frame", 5.0, 3.0, 4.5),
    "rcOmf": StructuralSystem("RC ordinary moment frame", 3.0, 3.0, 2.5),
    "rcSpecialWallFrame": StructuralSystem(
        "Building frame with RC special shear walls", 6.0, 2.5, 5.0
    ),
    "rcOrdinaryWallFrame": StructuralSystem(
        "Building frame with RC ordinary shear walls", 5.0, 2.5, 4.5
    ),
    "rcDualSpecial": StructuralSystem(
        "Dual: RC special moment frame and special shear walls", 7.0, 2.5, 5.5
    ),
    "steelSmf": StructuralSystem("Steel special moment frame", 8.0, 3.0, 5.5),
    "steelOmf": StructuralSystem("Steel ordinary moment frame", 3.5, 3.0, 3.0),
    "steelScbf": StructuralSystem("Steel special concentrically braced frame", 6.0, 2.0, 5.0),
}

#: Site classes (Table 6.2.13), from the soil profile of the soil report.
SITE_CLASSES = {
    "SA": "Rock (Vs > 800 m/s)",
    "SB": "Rock (360-800 m/s)",
    "SC": "Very dense soil or soft rock (180-360 m/s)",
    "SD": "Stiff soil (Vs < 180 m/s)",
    "SE": "Soft soil over stiffer layer",
}

#: Wind exposure categories (6.2.9.3): A - urban and suburban, B - open terrain, C - flat
#: unobstructed areas and water surfaces, including coastal belts.
EXPOSURES = {
    "A": "Urban, suburban, wooded",
    "B": "Open terrain, scattered obstructions",
    "C": "Flat open country, coastal",
}

#: Load cases of a building (2.1, 2.2.2): dead, superimposed dead, live, roof live, wind and
#: earthquake in the two plan directions.
LOAD_CASES = {
    "D": "Dead (self-weight)",
    "SD": "Superimposed dead (finishes, partitions)",
    "L": "Live",
    "Lr": "Roof live",
    "WX": "Wind in X",
    "WY": "Wind in Y",
    "EX": "Earthquake in X",
    "EY": "Earthquake in Y",
}

#: Strength design load combinations (2.7.3): (name, factors). D includes superimposed dead load.
STRENGTH_COMBINATIONS: list[tuple[str, dict[str, float]]] = [
    ("1.4D", {"D": 1.4}),
    ("1.2D + 1.6L + 0.5Lr", {"D": 1.2, "L": 1.6, "Lr": 0.5}),
    ("1.2D + 1.6Lr + 1.0L", {"D": 1.2, "Lr": 1.6, "L": 1.0}),
    ("1.2D + 1.6Lr + 0.8W", {"D": 1.2, "Lr": 1.6, "W": 0.8}),
    ("1.2D + 1.6W + 1.0L + 0.5Lr", {"D": 1.2, "W": 1.6, "L": 1.0, "Lr": 0.5}),
    ("1.2D + 1.0E + 1.0L", {"D": 1.2, "E": 1.0, "L": 1.0}),
    ("0.9D + 1.6W", {"D": 0.9, "W": 1.6}),
    ("0.9D + 1.0E", {"D": 0.9, "E": 1.0}),
]

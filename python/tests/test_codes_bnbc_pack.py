"""The built-in BNBC 2020 code pack holds exactly the values SAEngine used before code packs.

``OLD`` is a frozen copy of the constants as they were written in the modules (v0.0.42): every
value of the pack is checked against it, and against the module constants still in place, so a
pack edit that changes a result fails here first. :mod:`saengine.library.bnbc` reads the pack:
its public names keep their values, types and order.
"""

from __future__ import annotations

import json

import pytest

from saengine.codes import tables
from saengine.library import bnbc

PACK = tables.PACKS_DIR / "bnbc2020"

# ─────────────────────────── frozen copy of library/bnbc.py (v0.0.42) ───────────────────────────

OLD_ZONE_COEFFICIENT = {1: 0.12, 2: 0.20, 3: 0.28, 4: 0.36}
OLD_LOCATIONS = {
    "dhaka": ("Dhaka", 2, 65.7),
    "chattogram": ("Chattogram", 3, 80.0),
    "coxsbazar": ("Cox's Bazar", 3, 80.0),
    "khulna": ("Khulna", 1, 73.3),
    "rajshahi": ("Rajshahi", 1, 49.2),
    "sylhet": ("Sylhet", 4, 61.1),
    "barishal": ("Barishal", 1, 78.7),
    "rangpur": ("Rangpur", 3, 65.3),
    "mymensingh": ("Mymensingh", 4, 67.4),
    "cumilla": ("Cumilla", 2, 61.4),
}
OLD_OCCUPANCY = {
    "I": ("Low hazard to human life on failure (agricultural, minor storage)", 1.00, 0.87),
    "II": ("Standard occupancy (all buildings not in I, III or IV)", 1.00, 1.00),
    "III": ("Substantial hazard: assembly, schools, health care without surgery", 1.25, 1.15),
    "IV": ("Essential facilities: hospitals, fire and police stations, shelters", 1.50, 1.15),
}
OLD_AREA_USES = {
    "residential": ("Residential: rooms and private corridors", 2.0),
    "residentialPublic": ("Residential: public rooms and corridors", 4.8),
    "office": ("Office", 2.4),
    "officeLobby": ("Office: lobbies and first-floor corridors", 4.8),
    "corridorAbove": ("Corridors above the first floor", 3.8),
    "classroom": ("School: classrooms", 1.9),
    "hospitalWard": ("Hospital: patient rooms", 1.9),
    "operatingRoom": ("Hospital: operating rooms, laboratories", 2.9),
    "assemblyFixed": ("Assembly: fixed seats", 2.9),
    "assemblyMovable": ("Assembly: movable seats, lobbies", 4.8),
    "retailGround": ("Retail: first floor", 4.8),
    "retailUpper": ("Retail: upper floors", 3.6),
    "storageLight": ("Storage: light", 6.0),
    "storageHeavy": ("Storage: heavy", 12.0),
    "parking": ("Parking: passenger vehicles", 1.9),
    "stairs": ("Stairs and exits", 4.8),
    "roof": ("Roof: ordinary flat, pitched or curved", 1.0),
    "roofGarden": ("Roof: gardens and assembly use", 4.8),
}
OLD_SYSTEMS = {
    "rcSmf": ("RC special moment frame", 8.0, 3.0, 5.5),
    "rcImf": ("RC intermediate moment frame", 5.0, 3.0, 4.5),
    "rcOmf": ("RC ordinary moment frame", 3.0, 3.0, 2.5),
    "rcSpecialWallFrame": ("Building frame with RC special shear walls", 6.0, 2.5, 5.0),
    "rcOrdinaryWallFrame": ("Building frame with RC ordinary shear walls", 5.0, 2.5, 4.25),
    "rcDualSpecial": ("Dual: RC special moment frame and special shear walls", 7.0, 2.5, 5.5),
    "steelSmf": ("Steel special moment frame", 8.0, 3.0, 5.5),
    "steelOmf": ("Steel ordinary moment frame", 3.5, 3.0, 3.0),
    "steelScbf": ("Steel special concentrically braced frame", 6.0, 2.0, 5.0),
}
#: design/seismic_rules.py TABLE_6_2_19 (v0.0.44), now read from the pack (system_row):
#: (row, R, Omega0, Cd, height limits B/C/D, frame, specialWalls, concrete).
OLD_TABLE_6_2_19 = {
    "rcSmf": ("C.4 (p. 623)", 8.0, 3.0, 5.5, (None, None, None), "special", False, True),
    "rcImf": ("C.5 (p. 623)", 5.0, 3.0, 4.5, (None, None, 0.0), "intermediate", False, True),
    "rcOmf": (
        "C.5 [sic, the 6th row] (p. 623)",
        3.0,
        3.0,
        2.5,
        (None, 0.0, 0.0),
        "ordinary",
        False,
        True,
    ),
    "rcSpecialWallFrame": ("B.5 (p. 622)", 6.0, 2.5, 5.0, (None, None, 50.0), None, True, True),
    "rcOrdinaryWallFrame": ("B.6 (p. 622)", 5.0, 2.5, 4.25, (None, None, 0.0), None, False, True),
    "rcDualSpecial": ("D.3 (p. 623)", 7.0, 2.5, 5.5, (None, None, None), "special", True, True),
    "steelSmf": ("C.1 (p. 622)", 8.0, 3.0, 5.5, (None, None, None), None, False, False),
    "steelOmf": ("C.3 (p. 622)", 3.5, 3.0, 3.0, (None, None, 0.0), None, False, False),
    "steelScbf": ("B.3 (p. 622)", 6.0, 2.0, 5.0, (None, None, 50.0), None, False, False),
}
OLD_SITE_CLASSES = {
    "SA": "Rock or rock-like formation, at most 5 m of weaker material on top (Vs > 800 m/s)",
    "SB": "Very dense sand, gravel or very stiff clay (Vs 360-800 m/s, N > 50, su > 250 kPa)",
    "SC": "Dense or medium dense sand, gravel or stiff clay (Vs 180-360 m/s, N 15-50, "
    "su 70-250 kPa)",
    "SD": "Loose-to-medium cohesionless soil or soft-to-firm cohesive soil (Vs < 180 m/s, "
    "N < 15, su < 70 kPa)",
    "SE": "Surface alluvium of SC or SD, 5-20 m thick, on material with Vs > 800 m/s",
}
OLD_EXPOSURES = {
    "A": "Urban, suburban, wooded",
    "B": "Open terrain, scattered obstructions",
    "C": "Flat open country, coastal",
}
OLD_LOAD_CASES = {
    "D": "Dead (self-weight)",
    "SD": "Superimposed dead (finishes, partitions)",
    "L": "Live",
    "Lr": "Roof live",
    "WX": "Wind in X",
    "WY": "Wind in Y",
    "EX": "Earthquake in X",
    "EY": "Earthquake in Y",
    "F": "Fluids (equipment contents)",
    "T": "Temperature",
}
OLD_STRENGTH = [
    ("1.4D", {"D": 1.4}),
    ("1.2D + 1.6L + 0.5Lr", {"D": 1.2, "L": 1.6, "Lr": 0.5}),
    ("1.2D + 1.6Lr + 1.0L", {"D": 1.2, "Lr": 1.6, "L": 1.0}),
    ("1.2D + 1.6Lr + 0.8W", {"D": 1.2, "Lr": 1.6, "W": 0.8}),
    ("1.2D + 1.6W + 1.0L + 0.5Lr", {"D": 1.2, "W": 1.6, "L": 1.0, "Lr": 0.5}),
    ("1.2D + 1.0E + 1.0L", {"D": 1.2, "E": 1.0, "L": 1.0}),
    ("0.9D + 1.6W", {"D": 0.9, "W": 1.6}),
    ("0.9D + 1.0E", {"D": 0.9, "E": 1.0}),
]
OLD_SITE_FACTORS = {
    "SA": (1.00, 0.15, 0.40, 2.0),
    "SB": (1.20, 0.15, 0.50, 2.0),
    "SC": (1.15, 0.20, 0.60, 2.0),
    "SD": (1.35, 0.20, 0.80, 2.0),
    "SE": (1.40, 0.15, 0.50, 2.0),
}
OLD_PERIOD = {
    "concreteMomentFrame": (0.0466, 0.9),
    "steelMomentFrame": (0.0724, 0.8),
    "other": (0.0488, 0.75),
}
OLD_PERIOD_FAMILY = {
    "rcSmf": "concreteMomentFrame",
    "rcImf": "concreteMomentFrame",
    "rcOmf": "concreteMomentFrame",
    "steelSmf": "steelMomentFrame",
    "steelOmf": "steelMomentFrame",
}
OLD_EXPOSURE_PROFILES = {"A": (7.0, 365.76), "B": (9.5, 274.32), "C": (11.5, 213.36)}
OLD_SCALARS = {
    "EDITION": "BNBC 2020",
    "DAMPING_ETA": 1.0,
    "SEISMIC_LIVE_SHARE": 0.25,
    "WIND_KD": 0.85,
    "WIND_KZT": 1.0,
    "WIND_GUST": 0.85,
    "WIND_CP_WINDWARD": 0.8,
    "WIND_CP_LEEWARD": ((1.0, -0.5), (2.0, -0.3), (4.0, -0.2)),
}

# ────────────────────── frozen copy of the other modules' constants (v0.0.42) ──────────────────────

#: (module, name) -> value as written in the module.
#: Constants deleted from their modules, which read the pack instead: only the pack's value is
#: checked against the frozen copy.
PACK_ONLY = {
    ("saengine.fem.seismic_design", "_SDC"),
    ("saengine.fem.seismic_design", "ALLOWABLE_DRIFT"),
    ("saengine.design.seismic_rules", "REQUIRED_LEVEL"),
    ("saengine.design.seismic_rules", "FC_MIN"),
    ("saengine.design.seismic_rules", "FC_MAX_LIGHTWEIGHT"),
    ("saengine.design.seismic_rules", "LIGHTWEIGHT_DENSITY"),
    ("saengine.design.seismic_rules", "PERMITTED_FY"),
    ("saengine.design.seismic_rules", "FY_MAX"),
    ("saengine.design.seismic_rules", "GRADE_TOLERANCE"),
    ("saengine.design.seismic_rules", "FY_ACTUAL_MARGIN"),
    ("saengine.design.seismic_rules", "FY_RETEST_MARGIN"),
    ("saengine.design.seismic_rules", "FU_FY_MIN"),
    ("saengine.design.steel.members", "PHI_TY"),
    ("saengine.design.steel.members", "PHI_TR"),
    ("saengine.design.steel.members", "PHI_C"),
    ("saengine.design.steel.members", "PHI_B"),
    ("saengine.design.steel.members", "PHI_V"),
    ("saengine.design.steel.members", "KL_R_COMPRESSION"),
    ("saengine.design.steel.members", "L_R_TENSION"),
    ("saengine.design.slender", "CRACKED_COLUMN"),
    ("saengine.design.slender", "CRACKED_BEAM"),
    ("saengine.design.slender", "CRACKED_PLATE"),
    ("saengine.design.slender", "CRACKED_WALL"),
    ("saengine.fem.second_order", "ACI_FACTORS"),
}

OLD_MODULE_CONSTANTS = {
    ("saengine.fem.seismic_design", "MINIMUM_FRACTION"): 0.85,
    ("saengine.fem.seismic_design", "ACCIDENTAL_ECCENTRICITY"): 0.05,
    ("saengine.fem.seismic_design", "ORTHOGONAL_SHARE"): 0.30,
    ("saengine.fem.seismic_design", "MASS_PARTICIPATION"): 0.90,
    ("saengine.fem.seismic_design", "TORSION_IRREGULAR"): 1.2,
    ("saengine.fem.seismic_design", "TORSION_EXTREME"): 1.4,
    ("saengine.fem.seismic_design", "AX_LIMIT"): 3.0,
    ("saengine.fem.seismic_design", "_SDC"): {
        "SA": ("BCCD", "CDDD"),
        "SB": ("BCDD", "CDDD"),
        "SC": ("BCDD", "CDDD"),
        "SD": ("CDDD", "DDDD"),
        "SE": ("DDDD", "DDDD"),
    },
    ("saengine.fem.seismic_design", "ALLOWABLE_DRIFT"): {
        "I": 0.020,
        "II": 0.020,
        "III": 0.015,
        "IV": 0.010,
    },
    ("saengine.fem.seismic_design", "MOMENT_FRAMES"): frozenset(
        {"rcSmf", "rcImf", "rcOmf", "steelSmf", "steelOmf"}
    ),
    ("saengine.design.seismic_rules", "REQUIRED_LEVEL"): {
        "D": "special",
        "C": "intermediate",
        "B": "ordinary",
    },
    ("saengine.design.seismic_rules", "FC_MIN"): 21.0,
    ("saengine.design.seismic_rules", "FC_MAX_LIGHTWEIGHT"): 35.0,
    ("saengine.design.seismic_rules", "LIGHTWEIGHT_DENSITY"): 1850.0,
    ("saengine.design.seismic_rules", "PERMITTED_FY"): (275.0, 300.0, 350.0, 400.0, 420.0),
    ("saengine.design.seismic_rules", "FY_MAX"): 420.0,
    ("saengine.design.seismic_rules", "GRADE_TOLERANCE"): 0.02,
    ("saengine.design.seismic_rules", "FY_ACTUAL_MARGIN"): 125.0,
    ("saengine.design.seismic_rules", "FY_RETEST_MARGIN"): 20.0,
    ("saengine.design.seismic_rules", "FU_FY_MIN"): 1.25,
    ("saengine.design.rc", "EPS_CU"): 0.003,
    ("saengine.design.rc", "STEEL_E"): 200_000.0,
    ("saengine.design.rc", "PHI_TENSION"): 0.90,
    ("saengine.design.rc", "PHI_TIED"): 0.65,
    ("saengine.design.rc", "PHI_SPIRAL"): 0.75,
    ("saengine.design.rc", "PHI_SHEAR"): 0.75,
    ("saengine.design.rc", "FYT_SHEAR_MAX"): 420.0,
    ("saengine.design.rc", "SLENDERNESS_LIMIT"): 22.0,
    ("saengine.design.slab", "PHI_PUNCHING"): 0.75,
    ("saengine.design.slab", "EPS_T_MIN"): 0.004,
    ("saengine.design.slab", "_TABLE_8_3_1_1"): {
        280.0: (33.0, 36.0, 36.0),
        420.0: (30.0, 33.0, 33.0),
        520.0: (28.0, 31.0, 31.0),
    },
    ("saengine.design.bars", "DIAMETERS"): (10.0, 12.0, 16.0, 20.0, 25.0, 32.0),
    ("saengine.design.bars", "MAIN_DIAMETERS"): (12.0, 16.0, 20.0, 25.0, 32.0),
    ("saengine.design.bars", "COLUMN_DIAMETERS"): (16.0, 20.0, 25.0, 32.0),
    ("saengine.design.bars", "SLAB_DIAMETERS"): (10.0, 12.0, 16.0),
    ("saengine.design.bars", "STIRRUP_DIAMETERS"): (8.0, 10.0, 12.0),
    ("saengine.design.bars", "SPACING_STEP"): 25.0,
    ("saengine.design.bars", "MIN_SLAB_SPACING"): 100.0,
    ("saengine.design.bars", "MIN_STIRRUP_SPACING"): 75.0,
    ("saengine.design.bars", "RHO_MIN"): 0.01,
    ("saengine.design.bars", "RHO_MAX"): 0.08,
    ("saengine.design.bars", "BEAM_RATIO_MAX"): 0.04,
    ("saengine.design.walls", "RHO_SMALL_BARS"): (0.0012, 0.0020),
    ("saengine.design.walls", "RHO_OTHER_BARS"): (0.0015, 0.0025),
    ("saengine.design.walls", "SMALL_BAR_MAX"): 16.0,
    ("saengine.design.walls", "SMALL_BAR_FY"): 420.0,
    ("saengine.design.walls", "RHO_SHEAR"): 0.0025,
    ("saengine.design.walls", "TWO_LAYER_THICKNESS"): 250.0,
    ("saengine.design.walls", "SPACING_MAX"): 450.0,
    ("saengine.design.walls", "RELAXED_SHARE"): 0.083,
    ("saengine.design.walls", "TWO_CURTAIN_SHARE"): 0.17,
    ("saengine.design.walls", "DRIFT_MIN"): 0.007,
    ("saengine.design.walls", "STRESS_REQUIRED"): 0.2,
    ("saengine.design.walls", "STRESS_STOP"): 0.15,
    ("saengine.design.walls", "PHI_SHEAR_SEISMIC"): 0.60,
    ("saengine.design.walls", "PHI_DIAGONAL"): 0.85,
    ("saengine.design.walls", "FYT_CONFINEMENT_MAX"): 700.0,
    ("saengine.design.walls", "HX_MAX"): 350.0,
    ("saengine.design.walls", "WALL_DIAMETERS"): (10.0, 12.0, 16.0, 20.0),
    ("saengine.design.walls", "BOUNDARY_DIAMETERS"): (16.0, 20.0, 25.0, 32.0),
    ("saengine.design.walls", "HOOP_DIAMETERS"): (10.0, 12.0),
    ("saengine.design.ductile_members", "AXIAL_SHARE"): 0.10,
    ("saengine.design.ductile_members", "SMF_BEAM_RHO_MAX"): 0.025,
    ("saengine.design.ductile_members", "SMF_COLUMN_RHO"): (0.01, 0.06),
    ("saengine.design.ductile_members", "SMF_BEAM_MIN_WIDTH"): 250.0,
    ("saengine.design.ductile_members", "SMF_BEAM_MIN_RATIO"): 0.3,
    ("saengine.design.ductile_members", "SMF_COLUMN_MIN_DIMENSION"): 300.0,
    ("saengine.design.ductile_members", "SMF_COLUMN_MIN_RATIO"): 0.4,
    ("saengine.design.ductile_members", "FYT_CONFINEMENT_MAX"): 700.0,
    ("saengine.design.ductile_members", "HX_MAX"): 350.0,
    ("saengine.design.ductile_members", "UNSUPPORTED_CLEAR"): 150.0,
    ("saengine.design.ductile_members", "BEAM_FIRST_HOOP"): 50.0,
    ("saengine.design.ductile_joints", "PROBABLE_STRESS"): 1.25,
    ("saengine.design.ductile_joints", "STRONG_COLUMN_RATIO"): 1.2,
    ("saengine.design.ductile_joints", "AXIAL_LIMIT"): 0.1,
    ("saengine.design.ductile_joints", "PHI_JOINT"): 0.85,
    ("saengine.design.ductile_joints", "JOINT_GAMMA"): {
        4: 1.7,
        3: 1.2,
        "opposite": 1.2,
        "other": 1.0,
    },
    ("saengine.design.ductile_joints", "VC_ZERO_AXIAL"): 0.05,
    ("saengine.design.slender", "NONSWAY_Q"): 0.05,
    ("saengine.design.slender", "SWAY_LIMIT"): 22.0,
    ("saengine.design.slender", "NONSWAY_CAP"): 40.0,
    ("saengine.design.slender", "KLU_R_MAX"): 100.0,
    ("saengine.design.slender", "DELTA_S_MAX"): 1.5,
    ("saengine.design.slender", "MOMENT_RATIO_MAX"): 1.4,
    ("saengine.design.slender", "PHI_K"): 0.75,
    ("saengine.design.slender", "CRACKED_COLUMN"): 0.70,
    ("saengine.design.slender", "CRACKED_BEAM"): 0.35,
    ("saengine.design.slender", "CRACKED_PLATE"): 0.25,
    ("saengine.design.slender", "CRACKED_WALL"): 0.35,
    ("saengine.fem.second_order", "ACI_FACTORS"): {
        "column": 0.70,
        "beam": 0.35,
        "wallUncracked": 0.70,
        "wallCracked": 0.35,
        "slab": 0.25,
    },
    ("saengine.design.lintels", "LINTEL_DIAMETERS"): (10.0, 12.0, 16.0, 20.0, 25.0),
    ("saengine.design.lintels", "COVER"): 25.0,
    ("saengine.design.lintels", "MIN_BEARING"): 100.0,
    ("saengine.design.lintels", "BEARING"): 150.0,
    ("saengine.design.lintels", "DEFLECTION_RATIO"): 600.0,
    ("saengine.design.lintels", "PROBABLE"): 1.25,
    ("saengine.design.stairs", "COVER"): 20.0,
    ("saengine.design.stairs", "GRAVITY_COMBINATIONS"): (
        ("1.4D", 1.4, 0.0),
        ("1.2D + 1.6L", 1.2, 1.6),
    ),
    ("saengine.design.steel.members", "G"): 77_200.0,
    ("saengine.design.steel.members", "PHI_TY"): 0.90,
    ("saengine.design.steel.members", "PHI_TR"): 0.75,
    ("saengine.design.steel.members", "PHI_C"): 0.90,
    ("saengine.design.steel.members", "PHI_B"): 0.90,
    ("saengine.design.steel.members", "PHI_V"): 0.90,
    ("saengine.design.steel.members", "KL_R_COMPRESSION"): 150.0,
    ("saengine.design.steel.members", "L_R_TENSION"): 300.0,
    ("saengine.library.generator", "FLAT_DIVISORS"): {
        280.0: (33.0, 36.0, 36.0),
        420.0: (30.0, 33.0, 33.0),
        520.0: (28.0, 31.0, 31.0),
    },
    ("saengine.library.generator", "ONE_WAY_SLAB"): (20.0, 24.0, 28.0),
    ("saengine.library.generator", "BEAM"): (16.0, 18.5, 21.0),
    ("saengine.substructure.pilecap", "CAP_COVER"): 50.0,
    ("saengine.substructure.pilecap", "PHI_STM"): 0.75,
    ("saengine.substructure.pilecap", "TIE_ARM"): 0.9,
    ("saengine.substructure.pilecap", "BETA_CCC"): 1.0,
    ("saengine.substructure.pilecap", "BETA_CCT"): 0.8,
    ("saengine.substructure.piles", "TABLE_6_3_10A"): {
        "monument": (2.30, 3.00, 3.50, 4.00),
        "permanent": (2.00, 2.50, 2.80, 3.00),
        "temporary": (1.40, 2.00, 2.30, 2.80),
    },
    ("saengine.substructure.piles", "CONTROLS"): ("good", "normal", "poor", "veryPoor"),
    ("saengine.substructure.piles", "PARTIAL_SKIN"): 1.5,
    ("saengine.substructure.piles", "PARTIAL_BASE"): 3.0,
    ("saengine.substructure.piles", "SPT_FS"): 3.5,
    ("saengine.substructure.piles", "NO_LOAD_TEST_FS"): 3.0,
    ("saengine.substructure.piles", "LOAD_TEST_FS"): 2.0,
}


def t(name):
    return tables.builtin_table(name)


def _tuple(v):
    return tuple(_tuple(x) for x in v) if isinstance(v, list | tuple) else v


def _pack_value(module: str, name: str):
    """The pack's value of a module constant, in the module's shape."""
    s, c, d, m = t("seismic"), t("concrete"), t("detailing"), t("materials")
    phi, steel, f = t("factors").phi, t("steel"), t("foundations")
    walls_c, walls_d, sp, jo = c.walls, d.walls, d.special, d.joints
    sdc = s.designCategories.bySiteClass
    values = {
        "MINIMUM_FRACTION": s.minimumScale,
        "ACCIDENTAL_ECCENTRICITY": s.accidentalEccentricity,
        "ORTHOGONAL_SHARE": s.orthogonalShare,
        "MASS_PARTICIPATION": s.massParticipation,
        "TORSION_IRREGULAR": s.torsionIrregular,
        "TORSION_EXTREME": s.torsionExtreme,
        "AX_LIMIT": s.torsionAmplificationMax,
        "_SDC": {k: ("".join(v["I-III"]), "".join(v["IV"])) for k, v in sdc.items()},
        "ALLOWABLE_DRIFT": s.allowableDrift,
        "MOMENT_FRAMES": frozenset(k for k, v in s.systems.items() if v.momentFrame),
        "REQUIRED_LEVEL": s.requiredDetailing,
        "FC_MIN": m.seismicFcMin,
        "FC_MAX_LIGHTWEIGHT": m.lightweightFcMax,
        "LIGHTWEIGHT_DENSITY": m.lightweightDensity,
        "PERMITTED_FY": tuple(m.seismicRebarFy),
        "FY_MAX": m.seismicRebarFyMax,
        "GRADE_TOLERANCE": m.gradeTolerance,
        "FY_ACTUAL_MARGIN": m.fyActualMargin,
        "FY_RETEST_MARGIN": m.fyRetestMargin,
        "FU_FY_MIN": m.fuFyMin,
        "EPS_CU": m.concreteStrain,
        "STEEL_E": m.steelE,
        "PHI_TENSION": phi["tension"],
        "PHI_TIED": phi["compressionTied"],
        "PHI_SPIRAL": phi["compressionSpiral"],
        "PHI_SHEAR": phi["shear"],
        "FYT_SHEAR_MAX": c.fytShearMax,
        "SLENDERNESS_LIMIT": c.slendernessLimit,
        "PHI_PUNCHING": phi["punching"],
        "EPS_T_MIN": c.slabStrainMin,
        "_TABLE_8_3_1_1": c.twoWayThickness,
        "FLAT_DIVISORS": c.twoWayThickness,
        "ONE_WAY_SLAB": c.oneWaySlabThickness,
        "BEAM": c.beamThickness,
        "DIAMETERS": tuple(c.barDiameters["all"]),
        "MAIN_DIAMETERS": tuple(c.barDiameters["main"]),
        "COLUMN_DIAMETERS": tuple(c.barDiameters["column"]),
        "SLAB_DIAMETERS": tuple(c.barDiameters["slab"]),
        "STIRRUP_DIAMETERS": tuple(c.barDiameters["stirrup"]),
        "WALL_DIAMETERS": tuple(c.barDiameters["wall"]),
        "BOUNDARY_DIAMETERS": tuple(c.barDiameters["boundary"]),
        "HOOP_DIAMETERS": tuple(c.barDiameters["hoop"]),
        "LINTEL_DIAMETERS": tuple(c.barDiameters["lintel"]),
        "SPACING_STEP": c.spacingStep,
        "MIN_SLAB_SPACING": c.minSlabSpacing,
        "MIN_STIRRUP_SPACING": c.minStirrupSpacing,
        "RHO_MIN": c.columnRho[0],
        "RHO_MAX": c.columnRho[1],
        "BEAM_RATIO_MAX": c.beamRatioMax,
        "RHO_SMALL_BARS": _tuple(walls_c["rhoSmallBars"]),
        "RHO_OTHER_BARS": _tuple(walls_c["rhoOtherBars"]),
        "SMALL_BAR_MAX": walls_c["smallBarMax"],
        "SMALL_BAR_FY": walls_c["smallBarFy"],
        "RHO_SHEAR": walls_c["rhoShear"],
        "TWO_LAYER_THICKNESS": walls_c["twoLayerThickness"],
        "SPACING_MAX": walls_c["spacingMax"],
        "RELAXED_SHARE": walls_d["relaxedShare"],
        "TWO_CURTAIN_SHARE": walls_d["twoCurtainShare"],
        "DRIFT_MIN": walls_d["driftMin"],
        "STRESS_REQUIRED": walls_d["stressRequired"],
        "STRESS_STOP": walls_d["stressStop"],
        "PHI_SHEAR_SEISMIC": phi["shearSeismic"],
        "PHI_DIAGONAL": phi["diagonalCoupling"],
        "AXIAL_SHARE": sp["axialShare"],
        "SMF_BEAM_RHO_MAX": sp["beamRhoMax"],
        "SMF_COLUMN_RHO": _tuple(sp["columnRho"]),
        "SMF_BEAM_MIN_WIDTH": sp["beamMinWidth"],
        "SMF_BEAM_MIN_RATIO": sp["beamMinRatio"],
        "SMF_COLUMN_MIN_DIMENSION": sp["columnMinDimension"],
        "SMF_COLUMN_MIN_RATIO": sp["columnMinRatio"],
        "UNSUPPORTED_CLEAR": sp["unsupportedClear"],
        "BEAM_FIRST_HOOP": sp["beamFirstHoop"],
        "PROBABLE_STRESS": jo["probableStress"],
        "STRONG_COLUMN_RATIO": jo["strongColumnRatio"],
        "AXIAL_LIMIT": jo["axialLimit"],
        "PHI_JOINT": phi["joint"],
        "JOINT_GAMMA": {int(k) if k.isdigit() else k: v for k, v in jo["gamma"].items()},
        "VC_ZERO_AXIAL": jo["vcZeroAxial"],
        "NONSWAY_Q": c.slender["nonswayQ"],
        "SWAY_LIMIT": c.slender["swayLimit"],
        "NONSWAY_CAP": c.slender["nonswayCap"],
        "KLU_R_MAX": c.slender["kluRMax"],
        "DELTA_S_MAX": c.slender["deltaSMax"],
        "MOMENT_RATIO_MAX": c.slender["momentRatioMax"],
        "PHI_K": phi["stiffnessReduction"],
        "CRACKED_COLUMN": c.crackedStiffness["column"],
        "CRACKED_BEAM": c.crackedStiffness["beam"],
        "CRACKED_PLATE": c.crackedStiffness["plate"],
        "CRACKED_WALL": c.crackedStiffness["wall"],
        "ACI_FACTORS": {
            "column": c.crackedStiffness["column"],
            "beam": c.crackedStiffness["beam"],
            "wallUncracked": c.crackedStiffness["wallUncracked"],
            "wallCracked": c.crackedStiffness["wall"],
            "slab": c.crackedStiffness["plate"],
        },
        "MIN_BEARING": d.lintels["minBearing"],
        "BEARING": d.lintels["bearing"],
        "DEFLECTION_RATIO": d.lintels["deflectionRatio"],
        "PROBABLE": d.lintels["probable"],
        "GRAVITY_COMBINATIONS": tuple(
            (g.name, g.factors["D"], g.factors.get("L", 0.0)) for g in t("combinations").gravity
        ),
        "PHI_TY": steel.phi["tensionYield"],
        "PHI_TR": steel.phi["tensionRupture"],
        "PHI_C": steel.phi["compression"],
        "PHI_B": steel.phi["flexure"],
        "PHI_V": steel.phi["shear"],
        "KL_R_COMPRESSION": steel.slenderness["compression"],
        "L_R_TENSION": steel.slenderness["tension"],
        "PHI_STM": phi["strutAndTie"],
        "TIE_ARM": f.strutAndTie["tieArm"],
        "BETA_CCC": f.strutAndTie["betaCCC"],
        "BETA_CCT": f.strutAndTie["betaCCT"],
        "TABLE_6_3_10A": f.pileSafety,
        "CONTROLS": tuple(f.pileControls),
        "PARTIAL_SKIN": f.partialSkin,
        "PARTIAL_BASE": f.partialBase,
        "SPT_FS": f.sptSafety,
        "NO_LOAD_TEST_FS": f.noLoadTestSafety,
        "LOAD_TEST_FS": f.loadTestSafety,
    }
    if name == "COVER":
        return c.cover["lintel" if module.endswith("lintels") else "stair"]
    if name == "CAP_COVER":
        return c.cover["pileCap"]
    if name == "FYT_CONFINEMENT_MAX":
        return (walls_d if module.endswith("walls") else sp)["fytConfinementMax"]
    if name == "HX_MAX":
        return (walls_d if module.endswith("walls") else sp)["hxMax"]
    if name == "G":
        return m.steelShearModulus
    return values[name]


# ─────────────────────────────────────────────── tests ───────────────────────────────────────────────


def test_every_table_file_validates_and_is_registered():
    names = sorted(p.stem for p in (PACK / "data").glob("*.json"))
    assert names == sorted(tables.TABLE_MODELS)
    manifest = json.loads((PACK / "pack.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "bnbc2020" and manifest["extends"] is None
    assert sorted(manifest["covers"]) == names
    for name in names:
        table = tables.builtin_table(name)
        assert isinstance(table, tables.TABLE_MODELS[name])
        assert table.source, f"{name} names no source"
        schema = tables.table_schema(name)
        assert schema["type"] == "object"


def test_library_bnbc_keeps_every_public_value_type_and_order():
    assert bnbc.EDITION == OLD_SCALARS["EDITION"]
    assert bnbc.ZONE_COEFFICIENT == OLD_ZONE_COEFFICIENT
    assert list(bnbc.ZONE_COEFFICIENT) == [1, 2, 3, 4]
    assert {k: tuple(v) for k, v in bnbc.LOCATIONS.items()} == OLD_LOCATIONS
    assert list(bnbc.LOCATIONS) == list(OLD_LOCATIONS)
    assert isinstance(bnbc.LOCATIONS["dhaka"], bnbc.Location)
    assert bnbc.LOCATIONS["dhaka"].wind_speed == 65.7
    assert {k: tuple(v) for k, v in bnbc.OCCUPANCY_CATEGORIES.items()} == OLD_OCCUPANCY
    assert list(bnbc.OCCUPANCY_CATEGORIES) == list(OLD_OCCUPANCY)
    assert {k: tuple(v) for k, v in bnbc.AREA_USES.items()} == OLD_AREA_USES
    assert list(bnbc.AREA_USES) == list(OLD_AREA_USES)
    assert {k: tuple(v) for k, v in bnbc.STRUCTURAL_SYSTEMS.items()} == OLD_SYSTEMS
    assert list(bnbc.STRUCTURAL_SYSTEMS) == list(OLD_SYSTEMS)
    assert bnbc.STRUCTURAL_SYSTEMS["rcSmf"].omega == 3.0
    assert bnbc.SITE_CLASSES == OLD_SITE_CLASSES and list(bnbc.SITE_CLASSES) == list(
        OLD_SITE_CLASSES
    )
    assert bnbc.EXPOSURES == OLD_EXPOSURES
    assert bnbc.LOAD_CASES == OLD_LOAD_CASES and list(bnbc.LOAD_CASES) == list(OLD_LOAD_CASES)
    assert bnbc.STRENGTH_COMBINATIONS == OLD_STRENGTH
    assert [list(f) for _, f in bnbc.STRENGTH_COMBINATIONS] == [list(f) for _, f in OLD_STRENGTH]
    assert {k: tuple(v) for k, v in bnbc.SITE_FACTORS.items()} == OLD_SITE_FACTORS
    assert bnbc.SITE_FACTORS["SD"].s == 1.35
    assert bnbc.PERIOD_COEFFICIENTS == OLD_PERIOD
    assert bnbc.SYSTEM_PERIOD_FAMILY == OLD_PERIOD_FAMILY
    assert {k: tuple(v) for k, v in bnbc.EXPOSURE_PROFILES.items()} == OLD_EXPOSURE_PROFILES
    for name, value in OLD_SCALARS.items():
        assert getattr(bnbc, name) == value, name
        assert type(getattr(bnbc, name)) is type(value), name


def test_combinations_table_matches_the_old_combinations():
    c = t("combinations")
    assert [(x.name, x.factors) for x in c.strength] == OLD_STRENGTH
    from saengine.fem.thermal import strength_combinations_with_t

    assert [(x.name, x.factors) for x in c.temperature] == strength_combinations_with_t()
    assert c.seismicDeadUpper == 1.2 and c.seismicDeadLower == 0.9


def test_seismic_table_matches_the_old_system_rows_and_spectrum():
    from saengine.design.seismic_rules import system_row

    s = t("seismic")
    assert set(s.systems) == set(OLD_TABLE_6_2_19)
    for key, row in OLD_TABLE_6_2_19.items():
        current = system_row(key)
        assert current is not None
        assert tuple(current) == row
    assert system_row("notASystem") is None
    assert s.pgaFactor == 2 / 3 and s.verticalFactor == 0.5
    assert s.designCategories.aliases == {"S1": "SE", "S2": "SE"}


@pytest.mark.parametrize(("module", "name"), sorted(OLD_MODULE_CONSTANTS))
def test_pack_value_equals_the_old_module_constant(module, name):
    import importlib

    old = OLD_MODULE_CONSTANTS[(module, name)]
    assert _tuple(_pack_value(module, name)) == _tuple(old)
    if (module, name) in PACK_ONLY:
        assert not hasattr(importlib.import_module(module), name), "read it from the pack"
        return
    current = getattr(importlib.import_module(module), name)
    assert current == old, f"{module}.{name} changed in the module; update the pack and this copy"


def test_pack_files_carry_clause_references():
    for path in (PACK / "data").glob("*.json"):
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw.get("$sources"), path.name
        assert "BNBC" in raw["source"] or "SAEngine" in raw["source"], path.name


# ───────────────────────── a bad pack is rejected when it loads ─────────────────────────


def _rejected(name: str, data: dict) -> bool:
    from pydantic import ValidationError

    try:
        tables.validate_table(name, data)
    except ValidationError:
        return True
    return False


def _edited(name: str, edit) -> dict:
    data = t(name).model_dump()
    edit(data)
    return data


@pytest.mark.parametrize(
    ("name", "edit"),
    [
        ("concrete", lambda d: d["walls"].update(rhoShear="abc")),
        ("concrete", lambda d: d["walls"].pop("spacingMax")),
        ("concrete", lambda d: d["walls"].update(rhoShear=1.5)),
        ("concrete", lambda d: d["cover"].pop("lintel")),
        ("concrete", lambda d: d["crackedStiffness"].update(beam=0)),
        ("concrete", lambda d: d["slender"].update(kluRMax=-1)),
        ("concrete", lambda d: d["barDiameters"].update(main=[])),
        ("concrete", lambda d: d["barDiameters"].pop("stirrup")),
        ("concrete", lambda d: d.update(columnRho=(0.08, 0.01))),
        ("detailing", lambda d: d.update(special={})),
        ("detailing", lambda d: d["joints"].update(gamma={"four": "x"})),
        ("detailing", lambda d: d["joints"]["gamma"].pop("opposite")),
        ("detailing", lambda d: d["walls"].update(stressStop=0.3)),
        ("detailing", lambda d: d["walls"].update(hxMaxx=350.0)),  # a typo is not ignored
        ("detailing", lambda d: d.pop("lintels")),
        ("factors", lambda d: d.update(phi={"tension": 0.9})),
        ("factors", lambda d: d["phi"].update(shear=5.0)),
        ("factors", lambda d: d["phi"].update(extra=1.2)),
        ("steel", lambda d: d["phi"].update(flexure=0)),
        ("steel", lambda d: d["slenderness"].update(compresion=200.0)),
        ("steel", lambda d: d.update(netAreaMax=1.2)),
        ("foundations", lambda d: d["strutAndTie"].pop("betaCCT")),
    ],
)
def test_bad_values_are_rejected_by_the_models(name, edit):
    assert _rejected(name, _edited(name, edit))


def test_groups_read_as_attributes_and_keys():
    phi = t("factors").phi
    assert phi.shear == phi["shear"] == 0.75 and "punching" in phi and phi.get("nope") is None
    # a further φ (for a hook) is allowed, checked 0 < φ <= 1, and read by key
    extra = tables.validate_table("factors", _edited("factors", lambda d: d["phi"].update(x=0.5)))
    assert extra.phi["x"] == 0.5 and extra.phi.keys()[-1] == "x"
    with pytest.raises(KeyError):
        phi["nope"]
    assert dict(t("detailing").joints.items())["gamma"] == {
        "4": 1.7,
        "3": 1.2,
        "opposite": 1.2,
        "other": 1.0,
    }


def test_registry_lists_a_bad_pack_with_its_problem(tmp_path):
    registry = pytest.importorskip("saengine.codes.registry")
    folder = tmp_path / "bad-phi"
    (folder / "data").mkdir(parents=True)
    manifest = {
        "schema": "saengine.codePack/1",
        "id": "bad-phi",
        "name": "Bad phi",
        "extends": "bnbc2020",
        "covers": ["factors", "detailing"],
    }
    (folder / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    data = folder / "data"
    (data / "factors.json").write_text(json.dumps({"phi": {"shear": 5.0}}), encoding="utf-8")
    (data / "detailing.json").write_text(
        json.dumps({"walls": {"rhoShear": "abc"}}), encoding="utf-8"
    )
    info = registry.validate(folder)
    tables_with_problems = {p.table for p in info.problems if p.severity == "error"}
    assert {"factors", "detailing"} <= tables_with_problems, info.problems
    # the same pack with sensible values (merged over BNBC) has no problem
    (data / "factors.json").write_text(json.dumps({"phi": {"shear": 0.7}}), encoding="utf-8")
    (data / "detailing.json").write_text(
        json.dumps({"walls": {"driftMin": 0.008}}), encoding="utf-8"
    )
    info = registry.validate(folder)
    assert not [p for p in info.problems if p.severity == "error"], info.problems


def test_registry_resolves_the_same_values_when_available():
    registry = pytest.importorskip("saengine.codes.registry")
    pack = registry.load("bnbc2020")
    assert pack.edition == "BNBC 2020"
    assert pack.table("locations") == t("locations")
    assert pack.table("seismic") == t("seismic")
    assert pack.table("combinations") == t("combinations")


def test_cracked_factors_walls_uncracked_default_to_the_column_factor():
    from types import SimpleNamespace

    from saengine.codes.context import cracked_factors

    data = json.loads((PACK / "data" / "concrete.json").read_text(encoding="utf-8"))
    assert cracked_factors().walls(cracked=False) == data["crackedStiffness"]["wallUncracked"]
    del data["crackedStiffness"]["wallUncracked"]
    data["crackedStiffness"]["column"] = 0.8
    table = tables.validate_table("concrete", data)
    factors = cracked_factors(SimpleNamespace(table=lambda name: table))
    assert (factors.walls(cracked=False), factors.walls(cracked=True)) == (0.8, 0.35)
